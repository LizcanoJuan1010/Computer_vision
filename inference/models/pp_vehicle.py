"""
PP-Vehicle Model - Vehicle Detection and Plate Recognition
Uses same RT-DETR model as PP-Human, filtered for vehicle classes
"""
import os
import cv2
import numpy as np
import paddle
from ..config import config
from .lpr import LPRModel

# COCO class IDs for vehicles
VEHICLE_CLASSES = {
    2: 'car',
    5: 'bus', 
    7: 'truck',
    3: 'motorcycle'
}


class PPVehicleResult:
    """Result container for vehicle detection"""
    def __init__(self):
        self.boxes = []      # [[x1,y1,x2,y2], ...]
        self.id = []         # [track_id, ...]
        self.cls = []        # [class_id, ...]
        self.conf = []       # [score, ...]
        self.plates = {}     # {track_id/index: plate_text}
        self.vehicle_types = {} # {track_id/index: vehicle_type}


class PPVehicleModel:
    """
    Vehicle Detection using RT-DETR + LPR
    
    Shares the same RT-DETR model as human detection but filters
    for vehicle classes and runs LPR on each detected vehicle.
    """
    
    def __init__(self, model_dir=None, lpr_model=None):
        self.model_dir = model_dir or "/app/weights/human_det/exported"
        self.predictor = None
        self.lpr_model = lpr_model
        self.input_size = (640, 640)
        self.conf_threshold = 0.4
        self._next_track_id = 10000  # Start high to avoid collision with human IDs
        self._track_history = {}
        
    def load(self):
        """Load RT-DETR model for vehicle detection"""
        print(f"🚗 Loading PP-Vehicle (RT-DETR) from {self.model_dir}...", flush=True)
        
        # Check for exported model
        model_file = os.path.join(self.model_dir, "model.pdmodel")
        params_file = os.path.join(self.model_dir, "model.pdiparams")
        
        if not os.path.exists(model_file):
            # Try alternate paths
            alt_paths = [
                "/app/weights/human_det",
                "/app/PaddleDetection/output_inference/rtdetr_r18vd_6x_coco"
            ]
            for alt in alt_paths:
                model_file = os.path.join(alt, "model.pdmodel")
                params_file = os.path.join(alt, "model.pdiparams")
                if os.path.exists(model_file):
                    self.model_dir = alt
                    break
                    
        if not os.path.exists(model_file):
            print(f"❌ Vehicle model not found - will use stub mode", flush=True)
            return
            
        try:
            # Configure Paddle Inference
            paddle_config = paddle.inference.Config(model_file, params_file)
            
            if paddle.is_compiled_with_cuda():
                paddle_config.enable_use_gpu(512, 0)  # 512MB for vehicle
                
                if config.USE_TENSORRT:
                    paddle_config.enable_tensorrt_engine(
                        workspace_size=1 << 29,  # 512MB
                        max_batch_size=1,
                        min_subgraph_size=3,
                        precision_mode=paddle.inference.PrecisionType.Half,
                        use_static=False,
                        use_calib_mode=False
                    )
                    
                paddle_config.enable_memory_optim()
            else:
                paddle_config.disable_gpu()
                paddle_config.enable_mkldnn()
                
            self.predictor = paddle.inference.create_predictor(paddle_config)
            print(f"✅ PP-Vehicle Loaded.", flush=True)
            
        except Exception as e:
            print(f"❌ Failed to load PP-Vehicle: {e}", flush=True)
            self.predictor = None

    def predict(self, frames, camera_ids=None):
        """
        Detect vehicles and run LPR on each
        
        Args:
            frames: List of frames (numpy arrays)
            camera_ids: Optional camera IDs for tracking
            
        Returns:
            List of PPVehicleResult
        """
        if self.predictor is None:
            return [PPVehicleResult() for _ in (frames if isinstance(frames, list) else [frames])]
            
        if not isinstance(frames, list):
            frames = [frames]
            
        if len(frames) == 0:
            return []
            
        results = []
        
        for i, frame in enumerate(frames):
            result = PPVehicleResult()
            cam_id = camera_ids[i] if camera_ids else f"cam_{i}"
            
            try:
                # Preprocess
                img, scale_factor, im_shape = self._preprocess(frame)
                
                # Set inputs
                input_names = self.predictor.get_input_names()
                for name in input_names:
                    handle = self.predictor.get_input_handle(name)
                    if 'image' in name.lower() or 'im' == name:
                        handle.copy_from_cpu(img)
                    elif 'scale' in name.lower():
                        handle.copy_from_cpu(scale_factor)
                    elif 'shape' in name.lower():
                        handle.copy_from_cpu(im_shape)
                        
                # Run inference
                self.predictor.run()
                
                # Get outputs
                output_names = self.predictor.get_output_names()
                outputs = {}
                for name in output_names:
                    outputs[name] = self.predictor.get_output_handle(name).copy_to_cpu()
                    
                # Parse detections
                detections = self._parse_outputs(outputs, frame.shape[:2])
                
                # Filter for vehicles only
                vehicle_idx = 0
                for det in detections:
                    cls_id, score, x1, y1, x2, y2 = det
                    cls_id = int(cls_id)
                    
                    if cls_id in VEHICLE_CLASSES and score > self.conf_threshold:
                        track_id = self._assign_track_id(cam_id, [x1, y1, x2, y2])
                        
                        result.boxes.append([x1, y1, x2, y2])
                        result.id.append(track_id)
                        result.cls.append(cls_id)
                        result.conf.append(float(score))
                        result.vehicle_types[vehicle_idx] = VEHICLE_CLASSES[cls_id]
                        
                        # Run LPR on vehicle crop
                        if self.lpr_model:
                            x1i, y1i, x2i, y2i = map(int, [x1, y1, x2, y2])
                            h, w = frame.shape[:2]
                            x1i = max(0, min(x1i, w))
                            x2i = max(0, min(x2i, w))
                            y1i = max(0, min(y1i, h))
                            y2i = max(0, min(y2i, h))
                            
                            if (x2i - x1i) > 50 and (y2i - y1i) > 50:
                                crop = frame[y1i:y2i, x1i:x2i]
                                lpr_result = self.lpr_model.predict(crop)
                                if lpr_result.label:
                                    result.plates[vehicle_idx] = lpr_result.label
                                    
                        vehicle_idx += 1
                        
            except Exception as e:
                print(f"❌ PP-Vehicle inference error: {e}", flush=True)
                
            results.append(result)
            
        return results
        
    def _preprocess(self, frame):
        """Preprocess frame for RT-DETR"""
        h, w = frame.shape[:2]
        target_h, target_w = self.input_size
        
        resized = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        
        img = resized.astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        img = (img - mean) / std
        
        img = img.transpose((2, 0, 1))
        img = np.expand_dims(img, axis=0)
        img = np.ascontiguousarray(img)
        
        scale_factor = np.array([[float(target_h) / h, float(target_w) / w]], dtype=np.float32)
        im_shape = np.array([[float(target_h), float(target_w)]], dtype=np.float32)
        
        return img, scale_factor, im_shape
        
    def _parse_outputs(self, outputs, original_shape):
        """Parse RT-DETR outputs"""
        detections = []
        
        for name, tensor in outputs.items():
            if tensor.ndim == 2 and tensor.shape[1] == 6:
                for row in tensor:
                    if row[1] > 0.01:
                        detections.append(row.tolist())
            elif tensor.ndim == 3:
                for row in tensor[0]:
                    if row[1] > 0.01:
                        detections.append(row.tolist())
                        
        h, w = original_shape
        th, tw = self.input_size
        scale_x = w / tw
        scale_y = h / th
        
        scaled = []
        for det in detections:
            cls_id, score, x1, y1, x2, y2 = det
            scaled.append([
                cls_id, score,
                x1 * scale_x, y1 * scale_y,
                x2 * scale_x, y2 * scale_y
            ])
            
        return scaled
        
    def _assign_track_id(self, camera_id, box, iou_threshold=0.5):
        """Simple IOU-based tracking"""
        if camera_id not in self._track_history:
            self._track_history[camera_id] = {}
            
        best_match = None
        best_iou = 0.0
        
        for track_id, prev_box in self._track_history[camera_id].items():
            iou = self._compute_iou(box, prev_box)
            if iou > best_iou and iou > iou_threshold:
                best_iou = iou
                best_match = track_id
                
        if best_match is not None:
            self._track_history[camera_id][best_match] = box
            return best_match
        else:
            self._next_track_id += 1
            self._track_history[camera_id][self._next_track_id] = box
            return self._next_track_id
            
    def _compute_iou(self, box1, box2):
        """Compute IOU between two boxes"""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - inter
        
        return inter / union if union > 0 else 0
