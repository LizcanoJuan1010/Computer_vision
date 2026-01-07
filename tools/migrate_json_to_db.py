import json
import os
import psycopg2
from psycopg2.extras import execute_values
import uuid

# Configuration
CAMERAS_FILE = "ingest/cameras.json"
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5436")
DB_NAME = os.getenv("DB_NAME", "vigias")
DB_USER = os.getenv("DB_USER", "user")
DB_PASS = os.getenv("DB_PASSWORD", "password")

def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

def migrate():
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        
        # Load JSON
        if not os.path.exists(CAMERAS_FILE):
             print(f"File {CAMERAS_FILE} not found!")
             return
             
        with open(CAMERAS_FILE, 'r') as f:
            cameras = json.load(f)
            
        print(f"Found {len(cameras)} cameras to migrate.")
        
        for cam in cameras:
            print(f"Processing camera: {cam.get('name')} ({cam.get('id')})")
            
            # 1. Ensure Organization Exists
            org_slug = cam.get("org_slug", "vigias")
            cur.execute("SELECT id FROM organizations WHERE slug = %s", (org_slug,))
            res = cur.fetchone()
            if not res:
                print(f"Creating organization: {org_slug}")
                cur.execute("""
                    INSERT INTO organizations (slug, name, is_active)
                    VALUES (%s, %s, true)
                    RETURNING id
                """, (org_slug, org_slug.capitalize()))
                org_id = cur.fetchone()[0]
            else:
                org_id = res[0]
                
            # 2. Ensure Zone Exists
            zone_slug = cam.get("zone_slug", "default")
            cur.execute("SELECT id FROM org_zones WHERE organization_id = %s AND slug = %s", (org_id, zone_slug))
            res = cur.fetchone()
            if not res:
                print(f"Creating zone: {zone_slug}")
                cur.execute("""
                    INSERT INTO org_zones (organization_id, slug, name, is_active)
                    VALUES (%s, %s, %s, true)
                    RETURNING id
                """, (org_id, zone_slug, zone_slug.capitalize()))
                zone_id = cur.fetchone()[0]
            else:
                zone_id = res[0]
                
            # 3. Upsert Camera
            cam_id = cam.get("id")
            # Generate UUID if missing (old JSON format might not have it, but current one does)
            if not cam_id:
                cam_id = str(uuid.uuid4())
                
            rtsp_url = cam.get("url")
            name = cam.get("name")
            
            # Store 'services' and raw 'features' in meta_info just in case
            meta_info = {
                "services": cam.get("services", []),
                "original_features": cam.get("features", [])
            }
            
            cur.execute("""
                INSERT INTO cameras (id, name, rtsp_url, location_name, zone_id, meta_info, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, true)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    rtsp_url = EXCLUDED.rtsp_url,
                    zone_id = EXCLUDED.zone_id,
                    meta_info = EXCLUDED.meta_info,
                    updated_at = NOW()
            """, (cam_id, name, rtsp_url, zone_slug, zone_id, json.dumps(meta_info)))
            
            # 4. Create Camera AI Configs (Zones/Features)
            # Map JSON "zones" + "features" to camera_ai_configs
            
            # Check for specific configs in JSON
            # The JSON structure has: 
            # "zones": { "intrusion": { "points": ... }, "line_crossing": ... }
            # "features": ["face", "intrusion", ...]
            
            json_zones = cam.get("zones", {})
            features_list = cam.get("features", [])
            
            # Helper to create config
            def upsert_ai_config(event_type, roi=None, trigger=None):
                # Default settings
                severity = 'MEDIUM'
                confidence = 0.70
                debounce = 60
                
                # Try to upsert
                try:
                    cur.execute("""
                        INSERT INTO camera_ai_configs (camera_id, event_type, roi_polygon, default_severity, confidence_threshold, debounce_seconds, is_active)
                        VALUES (%s, %s, %s, %s, %s, %s, true)
                        ON CONFLICT (camera_id, event_type) DO UPDATE SET
                            roi_polygon = EXCLUDED.roi_polygon,
                            is_active = true
                    """, (cam_id, event_type, json.dumps(roi) if roi else None, severity, confidence, debounce))
                    print(f"  - Configured {event_type}")
                except Exception as e:
                    print(f"  - Error configuring {event_type}: {e}")

            # Process features list to ensure we have configs for them
            # Even if no specific zone points are defined (whole screen)
            for feat in features_list:
                # Check if this feature has specific zone definition
                if feat in json_zones:
                    z_data = json_zones[feat]
                    # Convert points [[x,y],...] to JSON format
                    # Note: JSON coords are likely pixel based if values > 1. 
                    # DB expects normalized 0-1? 
                    # Checking `cameras.json`:
                    # "points": [[289, 349], ...] -> These are pixels (640x360 base)
                    # We should normalize them for the DB!
                    
                    # Assuming 640x360 based on Ingest config
                    BASE_W = 640.0
                    BASE_H = 360.0
                    
                    raw_points = z_data.get("points", [])
                    norm_points = []
                    valid_norm = True
                    
                    for p in raw_points:
                        nx = p[0] / BASE_W
                        ny = p[1] / BASE_H
                        # Clamp to 0-1
                        nx = max(0.0, min(1.0, nx))
                        ny = max(0.0, min(1.0, ny))
                        norm_points.append([nx, ny])
                        
                    upsert_ai_config(feat, roi=norm_points, trigger=z_data.get("trigger"))
                else:
                     # Feature enabled but no zone -> Whole screen (ROI = None)
                     upsert_ai_config(feat, roi=None)
                     
            conn.commit()
            
        print("Migration completed successfully.")
        
    except Exception as e:
        print(f"Migration Failed: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    migrate()
