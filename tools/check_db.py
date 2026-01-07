import os
import psycopg2
import numpy as np

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5435")
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "vigias")

try:
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
    cur = conn.cursor()
    
    cur.execute("SELECT id, name, embedding FROM faces")
    rows = cur.fetchall()
    
    print(f"Found {len(rows)} faces in DB:")
    for row in rows:
        id, name, embedding = row
        # embedding is a list or string depending on how it's stored. pgvector stores as vector.
        # psycopg2 might return it as string or list.
        print(f"ID: {id}, Name: {name}, Embedding Length: {len(embedding) if embedding else 'None'}")
        
    cur.close()
    conn.close()

except Exception as e:
    print(f"Error: {e}")
