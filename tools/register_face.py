import cv2
import numpy as np
import argparse
import insightface
from insightface.app import FaceAnalysis
from inference.database import Database
from inference.config import config

def register_face(image_path, name):
    # 1. Initialize Model
    print("Loading InsightFace model...")
    app = FaceAnalysis(name=config.INSIGHTFACE_MODEL_NAME, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(640, 640))

    # 2. Read Image
    img = cv2.imread(image_path)
    if img is None:
        print(f"Error: Could not read image {image_path}")
        return

    # 3. Detect Face
    faces = app.get(img)
    if len(faces) == 0:
        print("Error: No face detected in the image.")
        return
    
    # Take the largest face if multiple
    face = sorted(faces, key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]))[-1]
    embedding = face.embedding

    # 4. Save to DB
    db = Database()
    try:
        db.connect()
        # Check if name exists
        db.cur.execute("SELECT id FROM faces WHERE name = %s", (name,))
        if db.cur.fetchone():
            print(f"Warning: User '{name}' already exists. Adding another embedding for better accuracy.")
        
        db.cur.execute("INSERT INTO faces (name, embedding) VALUES (%s, %s)", (name, embedding.tolist()))
        db.conn.commit()
        print(f"Successfully registered '{name}'!")
    except Exception as e:
        print(f"Database error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Register a face in the VIGIAS-IA database")
    parser.add_argument("image", help="Path to the image file containing the face")
    parser.add_argument("name", help="Name of the person")
    args = parser.parse_args()

    register_face(args.image, args.name)
