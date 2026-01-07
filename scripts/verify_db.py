import os
import psycopg2
from psycopg2 import sql

# Config
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5436") # Default to 5436 as per docker-compose
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "vigias")

def check_db():
    print(f"Checking Database connection to {DB_HOST}:{DB_PORT}...")
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cur = conn.cursor()
        
        # 1. Check Tables
        required_tables = ["cameras", "events", "alerts", "faces", "camera_stats"]
        print("\n[1] Checking Tables:")
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        existing_tables = [row[0] for row in cur.fetchall()]
        
        all_ok = True
        for table in required_tables:
            if table in existing_tables:
                print(f"  ✅ Table '{table}' exists.")
            else:
                print(f"  ❌ Table '{table}' MISSING!")
                all_ok = False
        
        # 2. Check Events Table Schema
        if "events" in existing_tables:
            print("\n[2] Checking 'events' table columns:")
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'events'
            """)
            columns = {row[0]: row[1] for row in cur.fetchall()}
            required_cols = ["track_id", "severity", "bbox", "confidence", "event_type"]
            for col in required_cols:
                if col in columns:
                    print(f"  ✅ Column '{col}' exists ({columns[col]}).")
                else:
                    print(f"  ❌ Column '{col}' MISSING!")
                    all_ok = False
                    
        conn.close()
        return all_ok
    except Exception as e:
        print(f"❌ Database Error: {e}")
        return False

if __name__ == "__main__":
    if check_db():
        print("\n✅ Database Verification PASSED")
    else:
        print("\n❌ Database Verification FAILED")
