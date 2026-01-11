import sys
import os

# Add /app to path to find modules
sys.path.append("/app")

print("🔍 Debugging Model Loading...", flush=True)

try:
    from inference.models.detection import RTDETRModel
    from inference.config import config
    
    model_path = config.PPHUMAN_DET_MODEL_DIR
    print(f"📂 Configured Path: {model_path}", flush=True)
    
    if os.path.exists(model_path):
        print(f"✅ File exists! Size: {os.path.getsize(model_path)} bytes", flush=True)
    else:
        print(f"❌ File NOT found at {model_path}", flush=True)
        # Check directory contents
        dir_path = os.path.dirname(model_path)
        if os.path.exists(dir_path):
            print(f"📂 Directory {dir_path} contents:", flush=True)
            print(os.listdir(dir_path))
        else:
            print(f"❌ Directory {dir_path} does not exist!", flush=True)
        sys.exit(1)

    print("🚀 Attempting to load model via ONNXRuntime...", flush=True)
    model = RTDETRModel(model_path)
    model.load()
    print("🎉 Success! Model loaded correctly.", flush=True)

except Exception as e:
    print(f"🔥 FATAL ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()
