import cv2
import numpy as np
import onnxruntime as ort
from ..config import config

class RTDETRModel:
    def __init__(self, model_path=None):
        self.model_path = model_path
        self.session = None
        self.input_name = None
        self.input_shape = (640, 640)
        
    def load(self):
        if not self.model_path:
            raise ValueError("Model path not set for RT-DETR ONNX")
            
        print(f"🚀 Loading RT-DETR ONNX: {self.model_path}")
        try:
            print("🔄 RT-DETR RELOADED [DEBUGv1]", flush=True)
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            self.session = ort.InferenceSession(self.model_path, providers=providers)
            
            # Get input details
            self.input_name = self.session.get_inputs()[0].name
            # Typically RT-DETR ONNX takes [1, 3, 640, 640] config
            # But let's verify if shape is fixed
            input_shape = self.session.get_inputs()[0].shape
            if len(input_shape) == 4:
                h = input_shape[2]
                w = input_shape[3]
                # Robustly handle symbolic dimensions (str, None, objects)
                try:
                    self.input_shape = (int(h), int(w))
                except (ValueError, TypeError):
                    print(f"⚠️ Symbolic input shape detected: {input_shape}. Defaulting to (640, 640).")
                    self.input_shape = (640, 640)
                
            print(f"✅ RT-DETR Loaded! Input: {self.input_name}, Shape: {self.input_shape}")
        except Exception as e:
            print(f"❌ Failed to load RT-DETR ONNX: {e}")
            raise e

    def preprocess(self, img):
        """
        Preprocess image for RT-DETR: Resize, Normalize, CHW format
        """
        # Resize
        h, w = self.input_shape
        # Ensure native int for OpenCV
        img_resized = cv2.resize(img, (int(w), int(h)))
        
        # Normalize (Standard ImageNet means usually, or 0-1)
        # RT-DETR usually expects 0-1 float, normalized
        img_data = img_resized.astype(np.float32) / 255.0
        
        # Transpose to [1, 3, H, W]
        img_data = img_data.transpose(2, 0, 1)
        img_data = np.expand_dims(img_data, axis=0)
        
        return img_data, img.shape[:2] # Return original shape for scaling back

    def predict(self, frame):
        """
        Run inference
        Returns: boxes (xyxy), scores, class_ids
        """
        if self.session is None:
            return [], [], []

        # Preprocess
        blob, (orig_h, orig_w) = self.preprocess(frame)
        
        # Inference
        # RT-DETR outputs: [1, 300, 4] (boxes) and [1, 300, 80] (scores) usually, OR post-processed
        # Let's handle generic ONNX output
        outputs = self.session.run(None, {self.input_name: blob})
        
        # Note: raw RT-DETR ONNX (from Paddle) usually exports with post-processing included
        # Output 0: boxes, Output 1: scores (sometimes concatenated)
        
        # Parse based on expected structure (simplifying for common RT-DETR export)
        # Assuming output is standard [1, N, 6] (x, y, x, y, score, cls) OR separated
        
        # Fallback parsing logic (to be adjusted based on actual ONNX signature):
        # We'll print shape on first run if debugging needed, but for now assuming standard Paddle export
        # usually gives 'reshape2_83.tmp_0' (boxes), 'tile_3.tmp_0' (scores) etc.
        # But lyuwenyu/RT-DETR exports might be clean.
        
        # Let's inspect output shapes dynamically
        # Common format for end-to-end DETR: [1, 300, 6] -> xyxy, score, cls
        
        return self._postprocess(outputs, (orig_h, orig_w))

    def _postprocess(self, outputs, orig_shape):
        orig_h, orig_w = orig_shape
        input_h, input_w = self.input_shape
        
        # Handle different output formats
        # Case A: Single output [1, N, 6] (xyxy, score, cls)
        # Case B: Boxes [1, N, 4], Scores [1, N, C]
        
        # Case B: Boxes [1, N, 4], Scores [1, N, C]
        
        final_boxes = []
        final_scores = []
        final_cls_ids = []
        detections = []
        # Removed debug prints
        
        if len(outputs) == 1 and outputs[0].shape[-1] == 6:
             # Already concat [N, 6]
            data = outputs[0][0] # [N, 6]
            
            if len(data) > 0:
                 scores = data[:, 4]
                 print(f"🕵️ DET Raw Max Score (Single): {scores.max():.4f}", flush=True) # DEBUG
                 mask = scores > config.DEFAULT_DET_CONFIDENCE
                 filtered = data[mask]
                 
                 for det in filtered:
                     x1, y1, x2, y2, score, cls_id = det
                     # Scale
                     x1 = x1 * (orig_w / input_w)
                     y1 = y1 * (orig_h / input_h)
                     x2 = x2 * (orig_w / input_w)
                     y2 = y2 * (orig_h / input_h)
                     final_boxes.append([x1, y1, x2, y2])
                     final_scores.append(score)
                     final_cls_ids.append(int(cls_id))

        elif len(outputs) >= 2:
             # Output 0: Scores [1, 300, 80]
             # Output 1: Boxes [1, 300, 4] (or vice versa, checked logs: 0 is 80, 1 is 4)
             
             # Check shapes to be sure
             out0 = outputs[0][0] # [300, 80] or [300, 4]
             out1 = outputs[1][0]
             
             raw_scores = None
             raw_boxes = None
             
             if out0.shape[-1] == 4:
                 raw_boxes = out0
                 raw_scores = out1
             else:
                 raw_scores = out0
                 raw_boxes = out1
                 
             # Process
             # 1. Get Max Score & Class for each box
             # raw_scores shape: [300, 80]
             max_scores = raw_scores.max(axis=1) # [300]
             cls_ids = raw_scores.argmax(axis=1) # [300]
             
             print(f"🕵️ DET Raw Max Score: {max_scores.max():.4f}", flush=True) # DEBUG
             
             # 2. Filter
             mask = max_scores > config.DEFAULT_DET_CONFIDENCE
             
             filtered_boxes = raw_boxes[mask]
             filtered_scores = max_scores[mask]
             filtered_cls = cls_ids[mask]

             if len(filtered_boxes) > 0:
                 print(f"DEBUG RT-DETR Raw Box[0]: {filtered_boxes[0]}", flush=True)
             
             # 3. Add to results
             # 3. Add to results
             # Check if boxes are normalized (0-1) or absolute (0-640)
             is_normalized = False
             if len(filtered_boxes) > 0:
                 if filtered_boxes.max() <= 1.0:
                     is_normalized = True

             for i in range(len(filtered_boxes)):
                 box = filtered_boxes[i]
                 score = filtered_scores[i]
                 cls_id = int(filtered_cls[i])
                 
                 # RT-DETR normalized output is [cx, cy, w, h]
                 # We need to convert to [x1, y1, x2, y2]
                 if is_normalized:
                     cx, cy, w, h = box
                     x1 = cx - w / 2
                     y1 = cy - h / 2
                     x2 = cx + w / 2
                     y2 = cy + h / 2
                     
                     # Scale to original image size
                     x1 *= orig_w
                     y1 *= orig_h
                     x2 *= orig_w
                     y2 *= orig_h
                 else:
                     # Fallback for absolute coordinates (legacy/unexpected)
                     x1, y1, x2, y2 = box
                     x1 = x1 * (orig_w / input_w)
                     y1 = y1 * (orig_h / input_h)
                     x2 = x2 * (orig_w / input_w)
                     y2 = y2 * (orig_h / input_h)
                 
                 final_boxes.append([x1, y1, x2, y2])
                 final_scores.append(score)
                 final_cls_ids.append(cls_id)
                 
        else:
             # Helper fallback
             pass

        return final_boxes, final_scores, final_cls_ids
