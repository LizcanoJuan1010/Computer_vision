import os
import cv2
import numpy as np
import onnxruntime as ort
from ..config import config

class PoseModel:
    """
    RTMPose-S ONNX Inference Wrapper
    """
    def __init__(self, model_path=None):
        self.model_path = model_path or "/app/weights/pose/end2end.onnx"
        self.session = None
        self.input_name = None
        self.output_names = []
        self.input_shape = (192, 256) # RTMPose-S standard resolution (w, h)

    def load(self):
        print(f"🚀 Loading RTMPose (ONNX) from {self.model_path}...", flush=True)
        if not os.path.exists(self.model_path):
            print(f"❌ Pose model not found at {self.model_path}", flush=True)
            return

        try:
            # ONNX Optimization: Create optimized session options
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
            sess_options.enable_mem_pattern = False
            sess_options.enable_cpu_mem_arena = True
            sess_options.intra_op_num_threads = 1  # Reduce CPU usage
            sess_options.inter_op_num_threads = 1  # Reduce CPU usage
            sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            
            providers = [
                ('CUDAExecutionProvider', {
                    'device_id': 0,
                    'arena_extend_strategy': 'kNextPowerOfTwo',
                    'cudnn_conv_algo_search': 'HEURISTIC',
                }),
                'CPUExecutionProvider'
            ]
            
            self.session = ort.InferenceSession(
                self.model_path, 
                sess_options=sess_options,
                providers=providers
            )
            
            self.input_name = self.session.get_inputs()[0].name
            for out in self.session.get_outputs():
                self.output_names.append(out.name)
                
            active = self.session.get_providers()
            print(f"✅ RTMPose Loaded! Input: {self.input_name}, Providers: {active}", flush=True)
        except Exception as e:
            print(f"❌ Failed to load RTMPose: {e}", flush=True)

    def predict(self, frames, boxes):
        """
        Predict keypoints for detected persons.
        frames: List of full images
        boxes: List of Lists of boxes [[x1,y1,x2,y2,score,cls], ...] per frame
        """
        if self.session is None:
            return []

        all_keypoints = []

        for i, frame in enumerate(frames):
            frame_boxes = boxes[i] if i < len(boxes) else []
            frame_kpts = []
            
            if len(frame_boxes) == 0:
                all_keypoints.append([])
                continue

            # Process each person crop
            for box in frame_boxes:
                # box format usually [x1, y1, x2, y2]
                x1, y1, x2, y2 = map(int, box[:4])
                
                # Expand box slightly for better pose estimation
                h, w = frame.shape[:2]
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(w, x2)
                y2 = min(h, y2)
                
                if x2 <= x1 or y2 <= y1:
                    frame_kpts.append(None)
                    continue

                crop = frame[y1:y2, x1:x2]
                
                # Preprocess
                input_tensor = self._preprocess(crop)
                
                # Inference
                outputs = self.session.run(self.output_names, {self.input_name: input_tensor})
                
                # Postprocess (simcc decoding usually handled inside end2end onnx or needs decoding)
                # If end2end.onnx, output should be [1, N, 3] (x, y, score) or similar
                kpts = outputs[0] # assuming first output is keypoints
                
                # Map back to original image coordinates
                # This depends heavily on the specific export of RTMPose. 
                # Assuming output is normalized or relative to crop input 256x192
                
                # TODO: Implement robust coordinate mapping based on specific ONNX output format
                # For now, placeholder for architecture integration
                frame_kpts.append(kpts)
            
            all_keypoints.append(frame_kpts)
            
        return all_keypoints

    def _preprocess(self, img):
        # Resize to 192x256 (WxH)
        resized = cv2.resize(img, self.input_shape)
        
        # Normalize
        mean = np.array([123.675, 116.28, 103.53])
        std = np.array([58.395, 57.12, 57.375])
        img = (resized - mean) / std
        
        # BHWC -> BCHW
        img = img.transpose(2, 0, 1)
        img = np.expand_dims(img, axis=0).astype(np.float32)
        return img
