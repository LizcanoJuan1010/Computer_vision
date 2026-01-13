
import cv2
import sys
import numpy as np
from models.lpr_onnx import LPRModelONNX, LPRResult

def test_image(image_path):
    print(f"🚀 Testing LPR on {image_path}...", flush=True)
    
    # Init Model
    model = LPRModelONNX()
    model.load()
    
    # Read Image
    img = cv2.imread(image_path)
    if img is None:
        print("❌ Could not read image", flush=True)
        return

    print(f"📏 Image Shape: {img.shape}", flush=True)
    
    # Run full predict
    # Note: predict() returns a LIST if input is LIST, or SINGLE object if input is single frame.
    # We pass single frame.
    result = model.predict(img, conf=0.01) # Ultra low conf to see EVERYTHING
    
    if isinstance(result, list):
         result = result[0]
         
    print(f"📊 Results found:", flush=True)
    print(f"   - Labels: {result.label}", flush=True)
    print(f"   - Conf: {result.conf}", flush=True)
    print(f"   - Boxes: {len(result.boxes)}", flush=True)
    
    if result.all_texts:
        print("   - All Candidates:", flush=True)
        for t, s in result.all_texts:
            print(f"     * '{t}' (Score: {s:.4f})", flush=True)
    else:
        print("   - No text candidates found by Recognition model.", flush=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_lpr.py <image_path>")
    else:
        test_image(sys.argv[1])
