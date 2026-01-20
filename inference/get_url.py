import psycopg2
import os

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_HOST = "postgres" # Internal
CONN_STR = "dbname=vigias user=user password=password host=postgres port=5432"

try:
    conn = psycopg2.connect(CONN_STR)
    cur = conn.cursor()
    cur.execute("SELECT id, rtsp_url, name FROM cameras WHERE id::text LIKE 'ee7433b9%' OR id::text LIKE '130dc442%'")
    rows = cur.fetchall()
    for row in rows:
        print(f"CAMERA: {row[2]} | ID: {row[0]}")
        print(f"URL: {row[1]}")
    conn.close()
except Exception as e:
    print(e)
