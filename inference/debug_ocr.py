import os
import paddle
from paddleocr import PaddleOCR
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

print("----------------------------------------------------------------", flush=True)
print(f"Paddle Version: {paddle.__version__}", flush=True)
print(f"Paddle Device: {paddle.get_device()}", flush=True)
print("----------------------------------------------------------------", flush=True)

try:
    print("Attempting to set device to CPU...", flush=True)
    paddle.set_device('cpu')
    print("Device set to CPU.", flush=True)
except Exception as e:
    print(f"Failed to set device: {e}", flush=True)

print("Initializing PaddleOCR...", flush=True)
try:
    # Try minimal init first
    ocr = PaddleOCR(use_angle_cls=True, lang='en')
    print("SUCCESS: PaddleOCR initialized!", flush=True)
    
    # Try with custom model paths if that worked
    print("Attempting with custom model paths...", flush=True)
    det_dir = "/app/weights/ocr/det"
    rec_dir = "/app/weights/ocr/rec"
    cls_dir = "/app/weights/ocr/cls"
    
    if os.path.exists(det_dir):
        ocr_custom = PaddleOCR(
            use_angle_cls=True,
            lang='en',
            det_model_dir=det_dir,
            rec_model_dir=rec_dir,
            cls_model_dir=cls_dir
        )
        print("SUCCESS: PaddleOCR initialized with custom models!", flush=True)
    else:
        print(f"WARNING: Custom model dir {det_dir} does not exist.", flush=True)

except Exception as e:
    print(f"CRASH/ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()

print("Script finished.", flush=True)
