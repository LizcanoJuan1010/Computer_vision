import os
import time
import subprocess
import glob
import psycopg2
from urllib.parse import urlparse

# Config
DB_HOST = os.getenv("POSTGRES_HOST", "postgres")
DB_USER = os.getenv("POSTGRES_USER", "user")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "password")
DB_NAME = os.getenv("POSTGRES_DB", "vision_db")
MEDIAMTX_HOST = os.getenv("MEDIAMTX_HOST", "mediamtx")
VIDEO_DIR = "/app/videos"

def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASS,
            dbname=DB_NAME
        )
    except Exception as e:
        print(f"❌ DB Connect Error: {e}")
        return None

    return None

def ensure_infrastructure(conn):
    """Ensure basic Org and Zone exist."""
    org_id = None
    zone_id = None
    try:
        with conn.cursor() as cur:
            # 1. Organization
            cur.execute("""
                INSERT INTO organizations (slug, name, is_active)
                VALUES ('sim_org', 'Simulation Corp', true)
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
            """)
            org_id = cur.fetchone()[0]
            
            # 2. Zone
            cur.execute("""
                INSERT INTO org_zones (slug, name, organization_id)
                VALUES ('sim_zone', 'Simulation Area', %s)
                ON CONFLICT (organization_id, slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
            """, (org_id,))
            zone_id = cur.fetchone()[0]
            
        conn.commit()
    except Exception as e:
        print(f"❌ Infra Setup Error: {e}")
        conn.rollback()
        
    return zone_id

def register_camera(video_name, rtsp_url):
    """Register the simulation camera in DB so Inference picks it up."""
    conn = get_db_connection()
    if not conn: return
    
    zone_id = ensure_infrastructure(conn)
    if not zone_id:
        print("❌ Could not get Zone ID")
        conn.close()
        return

    cam_id = f"sim_{video_name.replace('.', '_')}"
    import uuid
    cam_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, cam_id))
    
    # Determine features based on filename keywords
    features = [] 
    # Default always active?
    
    if "fight" in video_name.lower(): features.append("fighting")
    if "fall" in video_name.lower(): features.append("falling")
    if "car" in video_name.lower() or "traffic" in video_name.lower(): 
        features.append("vehicle") # Triggers LPR in some flows if configured? 
        # Schema: event_type. 'person' is standard. 'vehicle' too.
        # LPR is triggered if 'vehicle' is detected usually?
    if "attr" in video_name.lower(): 
        # Attributes are usually always on if Person is on? 
        # Schema `camera_ai_configs` defines EVENT TYPES (person, fire).
        # Attributes are metadata on 'person' event.
        # So we just ensure 'person' is active.
        pass
        
    if "reid" in video_name.lower(): pass
    
    # Always add 'person' default
    if "fighting" not in features and "falling" not in features:
        features.append("person")

    print(f"📝 Registering Camera {cam_uuid} ({video_name}) with events: {features}")
    
    try:
        with conn.cursor() as cur:
            # Upsert Camera
            # Schema: id, zone_id, name, rtsp_url, is_active
            cur.execute("""
                INSERT INTO cameras (id, zone_id, name, rtsp_url, is_active)
                VALUES (%s, %s, %s, %s, true)
                ON CONFLICT (id) DO UPDATE SET 
                    rtsp_url = EXCLUDED.rtsp_url,
                    is_active = true,
                    zone_id = EXCLUDED.zone_id;
            """, (cam_uuid, zone_id, f"Sim - {video_name}", rtsp_url))
            
            # Upsert AI Configs (One per event type)
            # Clean old configs first?
            cur.execute("DELETE FROM camera_ai_configs WHERE camera_id = %s", (cam_uuid,))
            
            for evt in features:
                cur.execute("""
                    INSERT INTO camera_ai_configs (camera_id, event_type, confidence_threshold, is_active)
                    VALUES (%s, %s, 0.6, true)
                    ON CONFLICT (camera_id, event_type) DO NOTHING
                """, (cam_uuid, evt))
                
            # Special case: If attributes needed, maybe add metadata to camera?
            # Current system reads 'features' from `get_camera_config_from_db`?
            # `get_camera_config_from_db` implementation in database.py returns a list of ai_configs via `json_agg`.
            # inference/main.py reads this.
            # pp_human.py lazy loading checks: 
            # if "fight_detection" in feats. 
            # Wait, `get_camera_config_from_db` query returns `event_type`.
            # So if I insert `event_type='fight_detection'`, `pp_human` will see it!
            # My `pp_human.py` checks: `["fight_detection", "fall_detection", ...]`
            # So I should map 'fighting' -> 'fight_detection' or ensure consistency.
            # In `pp_human.py`: `if any(f in feats for f in ["fight_detection", ...])`
            # So I should use "fight_detection" as event_type in DB.
            
            if "fight" in video_name.lower(): 
                 cur.execute("INSERT INTO camera_ai_configs (camera_id, event_type) VALUES (%s, 'fight_detection') ON CONFLICT DO NOTHING", (cam_uuid,))
            if "fall" in video_name.lower():
                 cur.execute("INSERT INTO camera_ai_configs (camera_id, event_type) VALUES (%s, 'fall_detection') ON CONFLICT DO NOTHING", (cam_uuid,))
            if "attr" in video_name.lower():
                 cur.execute("INSERT INTO camera_ai_configs (camera_id, event_type) VALUES (%s, 'human_attr') ON CONFLICT DO NOTHING", (cam_uuid,))
            if "reid" in video_name.lower():
                 cur.execute("INSERT INTO camera_ai_configs (camera_id, event_type) VALUES (%s, 'human_reid') ON CONFLICT DO NOTHING", (cam_uuid,))
            
        conn.commit()
        print(f"✅ Camera Registered: {cam_uuid}")
    except Exception as e:
        print(f"❌ DB Error: {e}")
        conn.rollback()
    finally:
        conn.close()

def main():
    print("🚀 Starting Simulator Service...")
    
    # Auto-Download Test Videos
    try:
        import download_videos
        print("📥 Checking for test videos...")
        download_videos.download_all()
    except Exception as e:
        print(f"⚠️ Video Download Error: {e}")
    
    # Wait for MediaMTX availability (simple sleep)
    time.sleep(10)
    
    processes = []
    
    while True:
        # Scan for videos
        videos = glob.glob(os.path.join(VIDEO_DIR, "*.*"))
        video_files = [v for v in videos if v.lower().endswith(('.mp4', '.avi', '.mkv', '.mov'))]
        
        if not video_files:
            print(f"💤 No videos found in {VIDEO_DIR}. Waiting...")
            time.sleep(10)
            continue
            
        for video_path in video_files:
            filename = os.path.basename(video_path)
            stream_name = filename.replace(" ", "_").replace(".", "_")
            rtsp_url = f"rtsp://{MEDIAMTX_HOST}:8554/{stream_name}"
            
            # Check if already running
            if any(p[0] == filename for p in processes):
                continue
                
            print(f"▶️ Starting Stream for {filename} -> {rtsp_url}")
            
            # Register in DB
            register_camera(filename, rtsp_url)
            
            # UDP is often better for local container streaming to avoid TCP buffer issues
            # But MediaMTX usually accepts TCP. We use TCP for reliability.
            # -re: Read input at native frame rate (Simulate live stream)
            # -stream_loop -1: Loop forever
            cmd = [
                "ffmpeg",
                "-re",
                "-stream_loop", "-1",
                "-i", video_path,
                "-c", "copy", # Copy codec (fastest, assumes H264)
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                rtsp_url
            ]
            
            try:
                # Transcode if necessary? 
                # If source is not h264, -c copy might fail for WebRTC/HLS consumption if browser doesn't support it.
                # Safer to transcode to h264 if CPU allows, or ensure source is h264.
                # Let's try COPY first for performance.
                p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                processes.append((filename, p))
            except Exception as e:
                print(f"❌ FFmpeg failed for {filename}: {e}")
        
        # Monitor processes
        for name, p in processes[:]:
            if p.poll() is not None:
                print(f"⚠️ Stream {name} died. Restarting in next loop.")
                processes.remove((name, p))
        
        time.sleep(5)

if __name__ == "__main__":
    main()
