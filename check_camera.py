import os
import sys

# Add path to find inference module
sys.path.append('/home/juan/dev/VIGIAS/VIGIAS-IA (PP-HUMAN)')

from inference.database import Database

def check_camera(cam_id):
    print(f"Checking camera: {cam_id}")
    db = Database()
    try:
        db.connect()
        with db.conn.cursor() as cur:
            # Try to match by text suffix since UUID is invalid
            suffix = "8e72-4660-a247-d631b234a72f"
            print(f"Searching for ID ending in: {suffix}...")
            cur.execute("SELECT id, name, is_active FROM cameras WHERE id::text LIKE %s", (f"%{suffix}",))
            row = cur.fetchone()
            if row:
                print(f"✅ Found in DB:")
                print(f"  Full ID: {row[0]}")
                print(f"  Name: {row[1]}")
                print(f"  Active: {row[2]}")
            else:
                print("❌ Camera NOT found in Database.")
                
            # Check total active
            cur.execute("SELECT count(*) FROM cameras WHERE is_active = true")
            count = cur.fetchone()[0]
            print(f"Total Active Cameras: {count}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    check_camera("e54a225-8e72-4660-a247-d631b234a72f")
