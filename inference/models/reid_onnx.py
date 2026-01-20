
import os
import cv2
import numpy as np
import onnxruntime as ort
from ..config import config

class ReIDModelONNX:
    """
    Person Re-Identification using ONNX Runtime
    Input: Person Crop (128, 256) or similar
    Output: Embedding Vector (256D or 512D)
    """
    def __init__(self, model_path=None):
        self.model_path = model_path or config.PPHUMAN_REID_ONNX
        self.session = None
        self.input_name = None
        self.input_shape = (128, 256) # Common ReID shape
        
    def load(self):
        print(f"🚀 Loading ReID (ONNX) from {self.model_path}...", flush=True)
        if not os.path.exists(self.model_path):
            print(f"⚠️ ReID model not found at {self.model_path}", flush=True)
            return

        try:
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = 1
            sess_options.inter_op_num_threads = 1
            sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL

            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            self.session = ort.InferenceSession(self.model_path, sess_options=sess_options, providers=providers)
            self.input_name = self.session.get_inputs()[0].name
            print(f"✅ ReID (ONNX) Loaded!", flush=True)
        except Exception as e:
            print(f"❌ Failed to load ReID ONNX: {e}", flush=True)

    def predict(self, frame, boxes):
        """
        Extract embeddings for person list
        """
        if self.session is None:
            return []
            
        embeddings = []
        for box in boxes:
            x1, y1, x2, y2 = map(int, box[:4])
            h, w = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            
            if x2 <= x1 or y2 <= y1:
                embeddings.append(None)
                continue
                
            crop = frame[y1:y2, x1:x2]
            blob = self._preprocess(crop)
            
            emb = self.session.run(None, {self.input_name: blob})[0]
            embeddings.append(emb / np.linalg.norm(emb)) # Normalize
            
        return embeddings

    def _preprocess(self, img):
        resized = cv2.resize(img, self.input_shape)
        # Standard PPLCNet Normalization
        mean = np.array([0.485, 0.456, 0.406])
        std = np.array([0.229, 0.224, 0.225])
        img = resized.astype(np.float32) / 255.0
        img = (img - mean) / std
        img = img.transpose(2, 0, 1)
        return np.expand_dims(img, axis=0).astype(np.float32)
