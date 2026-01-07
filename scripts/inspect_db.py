import os
import psycopg2
from psycopg2 import sql

# Config
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5436")
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "vigias")

def inspect_db():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cur = conn.cursor()
        
        # 1. Check Current User
        cur.execute("SELECT current_user, current_database(), version()")
        user, db, version = cur.fetchone()
        print(f"✅ Connected as User: '{user}' on Database: '{db}'")
        print(f"ℹ️  Version: {version.split()[0]}...")
        
        # 2. List Tables and Row Counts
        print("\n📊 Tables & Row Counts:")
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = [row[0] for row in cur.fetchall()]
        
        if not tables:
            print("   (No tables found)")
        
        for table in tables:
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
            count = cur.fetchone()[0]
            print(f"   - {table}: {count} rows")
            
        # 3. Show recent events
        if "events" in tables:
            print("\n🚨 Recent Events (Last 5):")
            cur.execute("SELECT id, event_type, track_id, created_at FROM events ORDER BY id DESC LIMIT 5")
            rows = cur.fetchall()
            if rows:
                for row in rows:
                    print(f"   - [{row[3]}] Type: {row[1]}, Track: {row[2]}")
            else:
                print("   (No events yet)")

        conn.close()
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    inspect_db()
