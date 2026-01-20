
import os
import cv2
import numpy as np
import onnxruntime as ort
from ..config import config

class VehicleAttributeModelONNX:
    """
    Vehicle Attribute Recognition (Color, Type)
    """
    def __init__(self, model_path=None):
        self.model_path = model_path or config.PPVEHICLE_ATTR_ONNX
        self.session = None
        self.input_name = None
        self.input_shape = (224, 224) # Standard for Vehicle Attr
        
        # Colors (PaddleClas order usually)
        self.colors = ["yellow", "orange", "green", "gray", "red", "blue", "white", "golden", "brown", "black"]
        self.types = ["sedan", "suv", "van", "hatchback", "mpv", "pickup", "bus", "truck", "estate"]

    def load(self):
        print(f"🚀 Loading Vehicle Attr (ONNX) from {self.model_path}...", flush=True)
        if not os.path.exists(self.model_path):
            print(f"⚠️ Vehicle Attr model not found", flush=True)
            return

        try:
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            self.session = ort.InferenceSession(self.model_path, providers=providers)
            self.input_name = self.session.get_inputs()[0].name
            print(f"✅ Vehicle Attr (ONNX) Loaded!", flush=True)
        except Exception as e:
            print(f"❌ Failed to load Vehicle Attr: {e}", flush=True)

    def predict(self, frame, boxes):
        if self.session is None: return []
        results = []
        for box in boxes:
            x1, y1, x2, y2 = map(int, box[:4])
            h, w = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0: 
                results.append({})
                continue
                
            blob = self._preprocess(crop)
            outputs = self.session.run(None, {self.input_name: blob})[0]
            
            # Postprocess (Argmax for Color and Type)
            # Assuming output is single vector [ColorScores..., TypeScores...]
            # Usually color is first 10, type is next 9.
            # This requires exact model spec verification. Placeholder:
            c_idx = np.argmax(outputs[0][:len(self.colors)])
            t_idx = np.argmax(outputs[0][len(self.colors):])
            
            results.append({
                "color": self.colors[c_idx] if c_idx < len(self.colors) else "unknown",
                "type": self.types[t_idx] if t_idx < len(self.types) else "unknown"
            })
        return results

    def _preprocess(self, img):
        resized = cv2.resize(img, self.input_shape)
        mean = np.array([0.485, 0.456, 0.406])
        std = np.array([0.229, 0.224, 0.225])
        img = resized.astype(np.float32) / 255.0
        img = (img - mean) / std
        img = img.transpose(2, 0, 1)
        return np.expand_dims(img, axis=0).astype(np.float32)
