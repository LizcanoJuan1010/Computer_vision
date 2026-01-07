import json
import os
import asyncio
import redis.asyncio as redis
import psycopg2
from psycopg2.extras import RealDictCursor

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5436")
DB_NAME = os.getenv("DB_NAME", "vigias")
DB_USER = os.getenv("DB_USER", "user")
DB_PASS = os.getenv("DB_PASSWORD", "password")

async def sync_config():
    try:
        # Connect to Redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        
        # Connect to DB
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        print("Fetching active cameras from Database...")
        cur.execute("""
            SELECT 
                c.id, c.name, c.rtsp_url as url, c.meta_info,
                o.slug as org_slug, o.id as org_id,
                z.slug as zone_slug, z.id as zone_id
            FROM cameras c
            JOIN org_zones z ON c.zone_id = z.id
            JOIN organizations o ON z.organization_id = o.id
            WHERE c.is_active = true
        """)
        
        cameras = cur.fetchall()
        print(f"Found {len(cameras)} active cameras.")
        
        for cam in cameras:
            cam_id = str(cam['id'])
            # Key format compatible with Router
            # Multi-tenant keys: config:org:{org}:zone:{zone}:camera:{id}
            # Fallback/Legacy: config:camera:{id}
            
            # We will set BOTH for compatibility during migration
            keys_to_set = [f"config:camera:{cam_id}"]
            if cam['org_slug'] and cam['zone_slug']:
                keys_to_set.append(f"config:org:{cam['org_slug']}:zone:{cam['zone_slug']}:camera:{cam_id}")
            
            # Handle URL placeholders
            raw_url = cam['url']
            final_url = replace_placeholders(raw_url)
            
            # Parse Services from meta_info
            services = ["security"]
            if cam['meta_info'] and 'services' in cam['meta_info']:
                services = cam['meta_info']['services']
                
            # Fetch AI Configs (Features & Zones)
            cur.execute("""
                SELECT event_type, roi_polygon, default_severity, confidence_threshold, debounce_seconds
                FROM camera_ai_configs
                WHERE camera_id = %s AND is_active = true
            """, (cam_id,))
            
            ai_configs = cur.fetchall()
            features = []
            zones = {}
            
            for ac in ai_configs:
                etype = ac['event_type']
                features.append(etype)
                
                # Transform ROI to "points"
                roi = ac['roi_polygon'] # already JSON decoded by psycopg2 if JSONB? Yes.
                
                # Determine trigger
                trigger = "enter"
                if etype == "line_crossing":
                    trigger = "in_out"
                    
                # Scale points if needed (Assuming 640x360 base for now)
                scaled_points = []
                if roi and isinstance(roi, list):
                    for p in roi:
                        if len(p) >= 2:
                            # Denormalize
                            x = int(p[0] * 640)
                            y = int(p[1] * 360)
                            scaled_points.append([x, y])
                            
                zones[etype] = {
                    "points": scaled_points,
                    "trigger": trigger,
                    "confidence": float(ac['confidence_threshold']),
                    "debounce": ac['debounce_seconds']
                }
            
            # Construct Payload
            payload = {
                "id": cam_id,
                "name": cam['name'],
                "url": final_url,
                "active": True,
                "org_slug": cam['org_slug'],
                "zone_slug": cam['zone_slug'],
                "org_id": str(cam['org_id']),
                "zone_id": str(cam['zone_id']),
                "services": services,
                "features": features,
                "zones": zones,
                # Include raw configs for forward compatibility
                "face_config": zones.get("face", {}),
                "intrusion_config": zones.get("intrusion", {}),
                "line_crossing_config": zones.get("line_crossing", {}),
                "yolo_config": zones.get("yolo", {})
            }
            
            payload_json = json.dumps(payload)
            
            for key in keys_to_set:
                await r.set(key, payload_json)
                # print(f"Updated {key}")
                
        print(f"Synced {len(cameras)} cameras to Redis.")
        await r.aclose()  # Use aclose() instead of deprecated close()
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"Error syncing config: {e}")

def replace_placeholders(url):
    replacements = {
        "{USER}": os.getenv("HIK_USER", "admin"),
        "{PASS}": os.getenv("HIK_PASS", "password"),
        "{IP}":   os.getenv("HIK_IP", "127.0.0.1"),
        "{PORT_RTSP}": os.getenv("PORT_RTSP", "554"),
        "{PORT_HTTP}": os.getenv("PORT_HTTP", "8080"),
    }
    for ph, val in replacements.items():
        if val:
            url = url.replace(ph, val)
    return os.path.expandvars(url)

if __name__ == "__main__":
    asyncio.run(sync_config())
