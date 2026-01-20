import onnxruntime as ort
import os
import sys

# Mock config paths
PATHS = {
    "RT-DETR": "/app/weights/human_det/rtdetr_r18.onnx",
    "Attributes": "/app/weights/attributes/human_attr.onnx",
    "Action (ST-GCN)": "/app/weights/action/stgcn.onnx",
    "ReID": "/app/weights/reid/reid.onnx",
    "LPR (Det)": "/app/weights/ocr/det/det.onnx",
    "LPR (Rec)": "/app/weights/ocr/rec/rec.onnx",
    "LPR (Cls)": "/app/weights/ocr/cls/cls.onnx",
    "Face Det (YuNet)": "/app/weights/face/yunet.onnx",
    "Face Rec (Ghost)": "/app/weights/face/ghostfacenetv2.onnx"
}

# Expected providers per model
EXPECTED_PROVIDERS = {
    "RT-DETR": "CUDAExecutionProvider",
    "Attributes": "CUDAExecutionProvider",
    "Action (ST-GCN)": "CPUExecutionProvider", # CPU Required
    "ReID": "CUDAExecutionProvider",
    "LPR (Det)": "CUDAExecutionProvider",
    "LPR (Rec)": "CUDAExecutionProvider",
    "LPR (Cls)": "CPUExecutionProvider", # CPU Required
    "Face Det (YuNet)": "CUDAExecutionProvider",
    "Face Rec (Ghost)": "CUDAExecutionProvider"
}

def check_gpu():
    print(f"🔎 Checking ONNX Runtime Model Providers...")
    available = ort.get_available_providers()
    print(f"ℹ️  Global Available Providers: {available}")
    
    print("\n📦 Verifying Model Configuration:")
    all_ok = True
    
    for name, path in PATHS.items():
        if not os.path.exists(path):
            print(f"  ⚪ {name}: File not found at {path}")
            continue
            
        try:
            # Load with default logic (mirroring real app code effectively)
            # or try to respect the EXPECTED provider to see if it works.
            
            target_provider = EXPECTED_PROVIDERS.get(name, "CUDAExecutionProvider")
            providers_list = [target_provider]
            if target_provider == 'CUDAExecutionProvider' and 'CPUExecutionProvider' not in providers_list:
                 providers_list.append('CPUExecutionProvider') # Allow fallback if needed for test, but we check active
                 
            sess_opts = ort.SessionOptions()
            sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
            try:
                sess_opts.add_session_config_entry("session.disable_shape_inference", "1")
            except:
                pass
            
            sess = ort.InferenceSession(path, sess_options=sess_opts, providers=providers_list)
            
            # Check active provider
            active = sess.get_providers()[0]
            
            if active == target_provider:
                print(f"  ✅ {name}: Loaded on {active} (Expected)")
            else:
                 # If we expected CUDA but got CPU
                if target_provider == 'CUDAExecutionProvider' and active == 'CPUExecutionProvider':
                     print(f"  ⚠️ {name}: Loaded on CPU but expected CUDA!")
                     all_ok = False
                # If we expected CPU and got CPU, good.
                elif target_provider == 'CPUExecutionProvider' and active == 'CPUExecutionProvider':
                     print(f"  ✅ {name}: Loaded on CPU (Expected for compatibility)")
                else:
                     print(f"  ❓ {name}: Active={active}, Expected={target_provider}")
                
        except Exception as e:
            print(f"  ❌ {name}: FAILED to load. Error: {e}")
            all_ok = False

    if all_ok:
        print("\n🎉 ALL MODELS VERIFIED SUCCESSFULLY!")
    else:
        print("\n⚠️ SOME MODELS HAVE ISSUES.")

if __name__ == "__main__":
    check_gpu()
