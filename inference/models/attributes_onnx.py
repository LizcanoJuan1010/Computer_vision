
import os
import cv2
import numpy as np
import onnxruntime as ort
from ..config import config

class AttributesModelONNX:
    """
    Human Attributes Recognition using ONNX Runtime (PPLCNet)
    Input: Person Crop (192, 256)
    Output: Binary attributes (Gender, Age, Glasses, etc.)
    """
    def __init__(self, model_path=None):
        # Default path relative to container
        self.model_path = model_path or config.PPHUMAN_ATTR_ONNX
        self.session = None
        self.input_name = None
        self.input_shape = (192, 256) # W, H
        
        # Attribute Definitions (Standard PPLCNet order)
        # Note: This depends on the specific PPLCNet version. 
        # Standard PP-Human attrs:
        # 0-9: Age (0-10, 11-20... 60+) - Softmax
        # 10: Gender (0: Female, 1: Male)
        # 11: Bag
        # 12: Glasses
        # 13: Hat
        # ... this varies. For StrongBaseline:
        # It usually outputs a single vector.
        
        # Simplified mapping (approximate for demo, needs verify with exact model version)
        self.attr_threshold = 0.5

    def load(self):
        print(f"🚀 Loading Human Attributes (ONNX) from {self.model_path}...", flush=True)
        if not os.path.exists(self.model_path):
            print(f"⚠️ Attributes model not found at {self.model_path}. Feature disabled.", flush=True)
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
            print(f"✅ Human Attributes (ONNX) Loaded!", flush=True)
        except Exception as e:
            print(f"❌ Failed to load Attributes ONNX: {e}", flush=True)

    def predict(self, crops):
        """
        Predict attributes for each person crop (list of numpy arrays)
        """
        if self.session is None or not crops:
            return []
            
        results = []
        
        for crop in crops:
            if crop.size == 0:
                results.append({})
                continue
            
            # Preprocess
            input_tensor = self._preprocess(crop)
            # Inference
            outputs = self.session.run(None, {self.input_name: input_tensor})
            output = outputs[0][0] # First batch
            
            # Postprocess (Sigmoid)
            # This part requires knowing the exact output structure of the model.
            # Assuming simple binary classification for now.
            attrs = self._postprocess(output)
            results.append(attrs)
            
        return results

    def _preprocess(self, img):
        # Resize
        resized = cv2.resize(img, self.input_shape) # 192, 256
        
        # Normalize (Mean/Std from PaddeClas)
        mean = np.array([0.485, 0.456, 0.406])
        std = np.array([0.229, 0.224, 0.225])
        
        img = resized.astype(np.float32) / 255.0
        img = (img - mean) / std
        
        # HWC -> CHW
        img = img.transpose(2, 0, 1)
        img = np.expand_dims(img, axis=0) # Add batch dim
        return img.astype(np.float32)

    def _postprocess(self, output):
        # Apply Sigmoid
        probs = 1 / (1 + np.exp(-output))
        
        # Dummy mapping (needs exact model metadata)
        # Assuming output size 26 (common for PA-100k or similar)
        res = {}
        
        # Example logic (placeholder)
        if len(probs) >= 23: 
            res['gender'] = "Male" if probs[21] > 0.5 else "Female"
            res['glasses'] = bool(probs[22] > 0.5)
            # ... add more mappings
            
        return res
