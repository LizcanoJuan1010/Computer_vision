import psycopg2
import os
import sys

# DB Config
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5436")
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "vigias")

CONN_STR = f"dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD} host={DB_HOST} port={DB_PORT}"

def enable_attr(partial_id):
    try:
        print(f"Connecting to {DB_HOST}:{DB_PORT}...")
        conn = psycopg2.connect(CONN_STR)
        cur = conn.cursor()
        
        # 1. Find Camera UUID
        print(f"🔍 Searching for camera matching '{partial_id}%'...")
        cur.execute("SELECT id, name FROM cameras WHERE id::text LIKE %s", (f"{partial_id}%",))
        res = cur.fetchall()
        
        if not res:
            print("❌ No camera found.")
            return
        
        if len(res) > 1:
            print(f"⚠️ Multiple cameras found: {res}. Please be more specific.")
            return
            
        cam_id, cam_name = res[0]
        print(f"✅ Found Camera: {cam_name} ({cam_id})")
        
        # 2. Check if config exists
        cur.execute("""
            SELECT id FROM camera_ai_configs 
            WHERE camera_id = %s AND event_type = 'human_attr'
        """, (cam_id,))
        
        existing = cur.fetchone()
        
        if existing:
            print("ℹ️ 'human_attr' config already exists. Updating to active...")
            cur.execute("""
                UPDATE camera_ai_configs 
                SET is_active = true 
                WHERE id = %s
            """, (existing[0],))
        else:
            print("✨ Inserting new 'human_attr' config...")
            cur.execute("""
                INSERT INTO camera_ai_configs (camera_id, event_type, is_active, confidence_threshold)
                VALUES (%s, 'human_attr', true, 0.6)
            """, (cam_id,))
            
        conn.commit()
        print("✅ Success! 'human_attr' enabled.")
        
        # Verify
        cur.execute("""
            SELECT event_type, is_active FROM camera_ai_configs WHERE camera_id = %s
        """, (cam_id,))
        print("📋 Current configs:")
        for row in cur.fetchall():
            print(f"   - {row[0]}: {'Active' if row[1] else 'Inactive'}")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "130dc442"
    enable_attr(target)
