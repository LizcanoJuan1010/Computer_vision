import torch
import sys

def log(msg):
    print(msg, flush=True)

try:
    path = "/app/weights/human_det/RTv4-S-hgnet.pth"
    log(f"Loading {path}...")
    
    # Try Ultralytics Load first (since user mentioned 'RT-DETR' and 'v4' sounds like maybe YOLO/Ultralytics versioning)
    try:
        from ultralytics import YOLO
        log("Attempting Ultralytics YOLO load...")
        model = YOLO(path)
        log("✅ Successfully loaded with Ultralytics!")
        log(f"Model task: {model.task}")
        # If this works, export is trivial
        sys.exit(0)
    except Exception as e:
        log(f"⚠️ Not an Ultralytics model: {e}")

    log("Attempting raw torch.load...")
    ckpt = torch.load(path, map_location='cpu')
    
    log("\nKeys in checkpoint:")
    if isinstance(ckpt, dict):
        log(list(ckpt.keys()))
        if 'model' in ckpt:
            log("\nModel state_dict keys (first 10):")
            keys = list(ckpt['model'].keys()) if isinstance(ckpt['model'], dict) else "model is not dict"
            log(keys[:10] if isinstance(keys, list) else keys)
            
            # Check for HGNet specific keys
            if any('hgnet' in str(k) for k in keys):
                log("✅ HGNet backbone detected in keys!")
                
        elif 'state_dict' in ckpt:
            log("\nState_dict keys (first 10):")
            keys = list(ckpt['state_dict'].keys())
            for k in keys[:10]:
                log(k)
        else:
            log("\nFirst 10 keys (flat dict?):")
            keys = list(ckpt.keys())
            for k in keys[:10]:
                log(k)
    else:
        log(f"Checkpoint is not a dict, it's a: {type(ckpt)}")

except Exception as e:
    log(f"\n❌ Error loading checkpoint: {e}")

