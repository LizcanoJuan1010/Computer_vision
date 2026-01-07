import psycopg2
import os

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5436")
DB_NAME = os.getenv("DB_NAME", "vigias_vision")
DB_USER = os.getenv("DB_USER", "vision_user")
DB_PASS = os.getenv("DB_PASSWORD", "vision_pass")

def fix_constraints():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        cur = conn.cursor()
        
        print("Checking/Fixing constraints...")
        
        # Check if unique constraint exists
        cur.execute("""
            SELECT 1 FROM pg_constraint 
            WHERE conname = 'unique_camera_event_config'
        """)
        
        if not cur.fetchone():
            print("Constraint 'unique_camera_event_config' missing. Adding it...")
            # First, we might need to remove duplicates if any exist
            cur.execute("""
                DELETE FROM camera_ai_configs c1
                USING camera_ai_configs c2
                WHERE c1.id > c2.id 
                AND c1.camera_id = c2.camera_id 
                AND c1.event_type = c2.event_type;
            """)
            
            cur.execute("""
                ALTER TABLE camera_ai_configs
                ADD CONSTRAINT unique_camera_event_config 
                UNIQUE (camera_id, event_type);
            """)
            print("Constraint added successfully.")
        else:
            print("Constraint 'unique_camera_event_config' already exists.")
            
        conn.commit()
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_constraints()
