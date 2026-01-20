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
        self.scale_input_name = 'scale_factor'
        
    def load(self):
        if not self.model_path:
            raise ValueError("Model path not set for RT-DETR ONNX")
            
        print(f"🚀 Loading RT-DETR/PP-YOLOE ONNX: {self.model_path}")
        try:
            # ONNX Optimization: Create optimized session options
            sess_options = ort.SessionOptions()
            # Re-enable optimization
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL # Re-enable optimization?
            # sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            # sess_options.intra_op_num_threads = 1
            
            # Provider configuration for optimal GPU usage
            providers = []
            
            if config.USE_TENSORRT:
                print(f"🚀 Enabling TensorRT Execution Provider (Precision: {config.TENSORRT_PRECISION})")
                trt_options = {
                    'device_id': 0,
                    'trt_fp16_enable': config.TENSORRT_PRECISION == 'fp16',
                    'trt_int8_enable': config.TENSORRT_PRECISION == 'int8',
                    'trt_engine_cache_enable': True,
                    'trt_engine_cache_path': '/app/inference/cache/trt_engines',
                }
                providers.append(('TensorrtExecutionProvider', trt_options))
                
            providers.append(('CUDAExecutionProvider', {
                'device_id': 0,
                'arena_extend_strategy': 'kNextPowerOfTwo',
                'cudnn_conv_algo_search': 'HEURISTIC',  # Faster than EXHAUSTIVE, less CPU
            }))
            providers.append('CPUExecutionProvider')
            
            self.session = ort.InferenceSession(
                self.model_path, 
                sess_options=sess_options,
                providers=providers
            )
            
            # Get input details
            inputs = self.session.get_inputs()
            self.input_name = inputs[0].name
            print(f"🔎 Model Inputs: {[i.name for i in inputs]}")
            
            # Check for scale_factor input
            self.scale_input_name = None
            for i in inputs:
                if 'scale' in i.name:
                    self.scale_input_name = i.name
                    print(f"🔎 Found scale input: {self.scale_input_name}")

            input_shape = inputs[0].shape
            if len(input_shape) == 4:
                h = input_shape[2]
                w = input_shape[3]
                try:
                    self.input_shape = (int(h), int(w))
                except (ValueError, TypeError):
                    print(f"⚠️ Symbolic input shape detected: {input_shape}. Defaulting to (640, 640).")
                    self.input_shape = (640, 640)
            
            active = self.session.get_providers()
            print(f"✅ Detection Model Loaded! Providers: {active}. Input: {self.input_name}, Shape: {self.input_shape}, ScaleInput: {self.scale_input_name}")
        except Exception as e:
            print(f"❌ Failed to load Detection ONNX: {e}")
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
        # PP-YOLOE / RT-DETR usually expects normalized with ImageNet mean/std
        img_data = img_resized.astype(np.float32) / 255.0
        
        # Mean/Std
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 1, 3)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 1, 3)
        img_data = (img_data - mean) / std
        
        # Transpose to [1, 3, H, W]
        img_data = img_data.transpose(2, 0, 1)
        img_data = np.expand_dims(img_data, axis=0)
        
        return img_data, img.shape[:2] # Return original shape for scaling back

    def predict(self, frame):
        """
        Run inference on a single frame
        Returns: boxes (xyxy), scores, class_ids
        """
        if self.session is None:
            return [], [], []

        # Preprocess
        blob, (orig_h, orig_w) = self.preprocess(frame)
        
        # Inputs dict
        input_feed = {self.input_name: blob}
        
        if self.scale_input_name:
            # PP-YOLOE expects scale_factor input
            # Usually [im_shape_h, im_shape_w] for Restore step
            # TRY FLOAT32 (Standard) -> If crash, maybe shape mismatch?
            scale_factor = np.array([[orig_h, orig_w]], dtype=np.float32) 
            input_feed[self.scale_input_name] = scale_factor
        # DEBUG: input_feed inputs
        print(f"🔄 DEBUG: input_feed inputs: {[k for k in input_feed.keys()]} Types: {[v.dtype for v in input_feed.values()]} Shapes: {[v.shape for v in input_feed.values()]}", flush=True)

        # CHECK for 'orig_target_sizes' (RT-DETRv4 specific)
        input_names = [i.name for i in self.session.get_inputs()]
        if "orig_target_sizes" in input_names:
             # Expects [Batch, 2] usually Int64
             # Format: [H, W] or [W, H]? 
             # DETR usually [H, W].
             sizes = np.array([[orig_h, orig_w]], dtype=np.int64)
             input_feed["orig_target_sizes"] = sizes

        # Inference
        print(f"🔄 DEBUG: Detection session.run() Input: {blob.shape}", flush=True)
        try:
             outputs = self.session.run(None, input_feed)
        except Exception as e:
             print(f"❌ Session Run FAILED: {e}", flush=True)
             return [], [], []

        print(f"🔄 DEBUG: Detection session.run() Finished", flush=True)
        
        return self._postprocess(outputs, (orig_h, orig_w))
        # return self._postprocess(outputs, (orig_h, orig_w))
        # return [], [], []

    def predict_batch(self, frames):
        """
        Run inference on a batch of frames in a single GPU call.
        """
        if self.session is None or not frames:
            return [([], [], []) for _ in frames] if frames else []
        
        # Preprocess all frames into a batch
        batch_blobs = []
        orig_shapes = []
        
        for frame in frames:
            blob, orig_shape = self.preprocess(frame)
            batch_blobs.append(blob[0])  # Remove batch dim (1, 3, H, W) -> (3, H, W)
            orig_shapes.append(orig_shape)
        
        # Stack into batch [N, 3, H, W]
        batch_input = np.stack(batch_blobs, axis=0)
        
        input_feed = {self.input_name: batch_input}
        
        if self.scale_input_name:
            # Batch scale factor [N, 2] -> [h, w] per image
            batch_scales = np.array([[h, w] for (h, w) in orig_shapes], dtype=np.float32)
            input_feed[self.scale_input_name] = batch_scales
        
        # Single inference call for entire batch
        # try:
        #     outputs = self.session.run(None, input_feed)
        # except Exception as e:
        #     print(f"⚠️ Batch inference failed, falling back to sequential: {e}", flush=True)
        #     # Fallback to sequential processing
        #     return [self.predict(frame) for frame in frames]
        
        # DEBUG: Force Sequential to avoid Segfault
        return [self.predict(frame) for frame in frames]
        
        # Postprocess each result is trickier with batch outputs if shape varies per image
        # Standard RT-DETR fixed output shape [N, 300, 6]
        # Let's use simple loop for simplicity unless verified
        
        # Slice outputs for batch
        # This part requires post-process to handle batch slicing.
        # Given current post-process is single-image oriented (takes orig_shape),
        # we can interpret outputs.
        # If output is [batch, 300, 6] we can iterate.
        return self._postprocess_batch(outputs, orig_shapes)

    def _postprocess_batch(self, outputs, orig_shapes):
        # Wrapper to handle batch output splitting
        # Assuming outputs[0] is [N, 300, 6] or similar
        batch_results = []
        N = len(orig_shapes)
        
        # Handle simple case: Output 0 is [N, ...]
        primary_out = outputs[0]
        
        for i in range(N):
            # Extract i-th element from all outputs
            single_outputs = []
            for out in outputs:
                if len(out.shape) >= 1 and out.shape[0] == N:
                     # Slice batch dimension
                     single_outputs.append(out[i:i+1]) # Keep dims [1, 300, ...] for postproc compatibility
                else:
                     # Broadcast or unknown, pass as is (rare)
                     single_outputs.append(out)
            
            res = self._postprocess(single_outputs, orig_shapes[i])
            batch_results.append(res)
            
        return batch_results
        results = []
        for i in range(len(frames)):
            try:
                # Extract output for this frame from batch
                frame_outputs = [out[i:i+1] for out in outputs]
                boxes, scores, cls_ids = self._postprocess(frame_outputs, orig_shapes[i])
                results.append((boxes, scores, cls_ids))
            except Exception as e:
                print(f"⚠️ Postprocess error for frame {i}: {e}", flush=True)
                results.append(([], [], []))
        
        return results

    def _postprocess(self, outputs, orig_shape):
        orig_h, orig_w = orig_shape
        input_h, input_w = self.input_shape
        
        # Verbose log for all outputs
        print(f"🔍 DEBUG DET: Outputs count = {len(outputs)}", flush=True)
        for i, out in enumerate(outputs):
            if hasattr(out, 'shape'):
                print(f"   - Output {i} shape: {out.shape}", flush=True)
            else:
                print(f"   - Output {i} type: {type(out)}", flush=True)

        final_boxes = []
        final_scores = []
        final_cls_ids = []
        
        # Check for empty output (no detections)
        if len(outputs) > 0 and hasattr(outputs[0], 'shape') and len(outputs[0]) == 0:
            print("🕵️ DET: Empty output detected (0 items). returning empty.", flush=True)
            return [], [], []

        # Determine Output Type based on First Output Shape
        out0 = outputs[0]
        # Handle Batch Dim if present [1, N, C] -> [N, C]
        if len(out0.shape) == 3 and out0.shape[0] == 1:
            out0 = out0[0]

        is_concatenated = (out0.shape[-1] == 6) # [x1, y1, x2, y2, score, cls]
        
        if is_concatenated:
            # Case A: Concatenated Output [N, 6] (PP-YOLOE, RT-DETR Matrix NMS)
            # We ignore the second output (Count) if present
            data = out0
            print(f"🕵️ DET Case A (Concatenated): Shape {data.shape}", flush=True)
            
            if len(data) > 0:
                 scores = data[:, 4]
                 print(f"🕵️ DET Case A: Max Raw Score = {scores.max():.4f}", flush=True)
                 mask = scores > config.DEFAULT_DET_CONFIDENCE
                 filtered = data[mask]
                 
                 for det in filtered:
                     if len(det) < 6: continue
                     x1, y1, x2, y2, score, cls_id = det[:6]
                     # Scale
                     nx1 = x1 * (orig_w / input_w)
                     ny1 = y1 * (orig_h / input_h)
                     nx2 = x2 * (orig_w / input_w)
                     ny2 = y2 * (orig_h / input_h)
                     final_boxes.append([nx1, ny1, nx2, ny2])
                     final_scores.append(float(score))
                     final_cls_ids.append(int(cls_id))

        elif len(outputs) >= 2:
            # Case B: Multi-output [Scores, Boxes] (RT-DETR Standard, etc)
            out1 = outputs[1]
            if len(out1.shape) == 3 and out1.shape[0] == 1: out1 = out1[0]
            
            # Identify which is boxes (last dim = 4)
            if out0.shape[-1] == 4:
                raw_boxes, raw_scores = out0, out1
            elif out1.shape[-1] == 4:
                raw_scores, raw_boxes = out0, out1
            else:
                print("❌ DET: Unknown output output shapes for Case B", flush=True)
                return [], [], []
            
            print(f"🕵️ DET Case B (Split): Boxes={raw_boxes.shape}, Scores={raw_scores.shape}", flush=True)

            # Safety check
            if len(raw_boxes) == 0:
                 return [], [], []

            if len(raw_scores.shape) == 2:
                # [N, C] logits
                max_logits = raw_scores.max(axis=1)
                # print(f"🕵️ DET Case B Max Logit: {max_logits.max():.4f}", flush=True)
                max_probs = 1.0 / (1.0 + np.exp(-raw_scores))
                max_scores = max_probs.max(axis=1)
                cls_ids = max_probs.argmax(axis=1)
                print(f"🕵️ DET Case B Max Prob: {max_scores.max():.4f}", flush=True)
            else:
                # [N] or [N, 1]
                max_logits = raw_scores.flatten()
                max_scores = 1.0 / (1.0 + np.exp(-max_logits))
                cls_ids = np.zeros_like(max_scores)
                # print(f"🕵️ DET Case B Simple Max Prob: {max_scores.max():.4f}", flush=True)
            
            mask = max_scores > config.DEFAULT_DET_CONFIDENCE
            filtered_boxes = raw_boxes[mask]
            filtered_scores = max_scores[mask]
            filtered_cls = cls_ids[mask]

            for i in range(len(filtered_boxes)):
                box = filtered_boxes[i]
                score = float(filtered_scores[i])
                cls_id = int(filtered_cls[i])
                
                # RT-DETR / COCO format is usually [cx, cy, w, h] normalized
                if box.max() <= 1.01:
                    cx, cy, w, h = box[0]*orig_w, box[1]*orig_h, box[2]*orig_w, box[3]*orig_h
                else:
                    cx, cy, w, h = box[0]*(orig_w/input_w), box[1]*(orig_h/input_h), box[2]*(orig_w/input_w), box[3]*(orig_h/input_h)
                
                # Convert CXCYWH -> XYXY
                x1 = cx - w/2
                y1 = cy - h/2
                x2 = cx + w/2
                y2 = cy + h/2
                
                final_boxes.append([x1, y1, x2, y2])
                final_scores.append(score)
                final_cls_ids.append(cls_id)
                print(f"🎯 DETECTED [{cls_id}]: {score:.4f} at {[int(x1), int(y1), int(x2), int(y2)]}", flush=True)

        return final_boxes, final_scores, final_cls_ids
