import os
import cv2
import glob
from .database import Database
from .models.face import FaceModel

def load_blacklist(face_model: FaceModel):
    blacklist_dir = "black_list"
    if not os.path.exists(blacklist_dir):
        print(f"Blacklist directory {blacklist_dir} not found. Skipping.")
        return

    print("Scanning 'black_list' for new faces...")
    
    db = Database()
    try:
        db.connect()
    except Exception as e:
        print(f"DB Connection failed during blacklist loading: {e}")
        return

    # Supported extensions
    extensions = ['*.jpg', '*.jpeg', '*.png']
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(blacklist_dir, ext)))

    for file_path in files:
        # Name is filename without extension
        name = os.path.splitext(os.path.basename(file_path))[0]
        
        # Check if already exists
        db.cur.execute("SELECT id FROM faces WHERE name = %s", (name,))
        if db.cur.fetchone():
            # Skip if exists (simplification for MVP)
            continue

        print(f"Registering {name} from {file_path}...")
        img = cv2.imread(file_path)
        if img is None:
            print(f"Failed to read {file_path}")
            continue

        faces = face_model.predict(img)
        if not faces:
            print(f"No face detected in {file_path}")
            continue
        
        # Take largest face
        face = sorted(faces, key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]))[-1]
        
        try:
            db.cur.execute("INSERT INTO faces (name, embedding) VALUES (%s, %s)", (name, face.embedding.tolist()))
            db.conn.commit()
            print(f"Successfully registered {name}")
        except Exception as e:
            print(f"Error registering {name}: {e}")

    db.close()
