import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5436") # Default to 5436 as per docker-compose
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "vigias")

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "schema.sql")

def run_sql_file(cursor, sql_file):
    print(f"Executing {sql_file}...")
    with open(sql_file, "r") as f:
        sql = f.read()
        cursor.execute(sql)
    print("Done.")

def main():
    print(f"Connecting to {DB_NAME} at {DB_HOST}:{DB_PORT}...")
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        
        run_sql_file(cur, SCHEMA_FILE)
        
        cur.close()
        conn.close()
        print("Database initialized successfully.")
        
    except psycopg2.OperationalError as e:
        print(f"Connection failed: {e}")
        print("Please check if the database container is running and the port is correct.")
        print(f"Current settings: Host={DB_HOST}, Port={DB_PORT}, User={DB_USER}, DB={DB_NAME}")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
