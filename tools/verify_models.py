
import sys
import os
sys.path.append(os.getcwd())

from inference.models.face import FaceModel
from inference.config import config
import cv2

def test_models():
    print("Testing model loading...")
    
    # Check Files
    print(f"Checking {config.FACE_DET_MODEL_PATH}...")
    if not os.path.exists(config.FACE_DET_MODEL_PATH):
        print("FAIL: YuNet model not found")
        return
        
    print(f"Checking {config.FACE_REC_MODEL_PATH}...")
    if not os.path.exists(config.FACE_REC_MODEL_PATH):
        print("FAIL: GhostFaceNet model not found")
        return

    # Load Face Model
    try:
        print("Attempting to load models via FaceModel class...")
        fm = FaceModel()
        fm.load()
        print("SUCCESS: Models loaded correctly!")
    except Exception as e:
        print(f"FAIL: Error loading models: {e}")

if __name__ == "__main__":
    test_models()
