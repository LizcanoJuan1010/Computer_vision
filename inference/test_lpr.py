
import cv2
import sys
import numpy as np
from models.lpr_onnx import LPRModelONNX

def test_image(image_path):
    print(f"🚀 Testing LPR on {image_path}...")
    
    # Init Model
    model = LPRModelONNX()
    model.load()
    
    # Read Image
    img = cv2.imread(image_path)
    if img is None:
        print("❌ Could not read image")
        return

    print(f"📏 Image Shape: {img.shape}")
    
    # Predict
    # Just call predict directly, it handles detection + recognition
    
    # Run full predict
    lpr_results = model.predict(img, conf=0.01) # Ultra low conf for test
    
    # Check candidates
    print(f"📊 Results found: {len(lpr_results)}")
    
    for i, res in enumerate(lpr_results):
        print(f"--- Result {i} ---")
        print(f"  Boxes: {res.boxes}")
        print(f"  Label: {res.label}")
        print(f"  Conf: {res.conf}")
        print(f"  All Texts: {res.all_texts}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_lpr.py <image_path>")
    else:
        test_image(sys.argv[1])
