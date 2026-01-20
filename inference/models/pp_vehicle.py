"""
PP-Vehicle Model - Vehicle Detection and Plate Recognition
Uses same RT-DETR model as PP-Human, filtered for vehicle classes
"""
import os
import cv2
import numpy as np
# Note: paddle import removed - not needed for ONNX inference

from ..config import config
import time
# Note: lpr_model is passed as instance, not imported here
from .detection import RTDETRModel  # Import ONNX backend
from .vehicle_attr_onnx import VehicleAttributeModelONNX

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
        self.attributes = {}    # {track_id/index: {color, type}}


class PPVehicleModel:
    """
    Vehicle Detection using RT-DETR (ONNX) + LPR + Attributes
    """
    
    def __init__(self, model_dir=None, lpr_model=None):
        # Default to ONNX path
        self.model_path = model_dir or config.PPHUMAN_DET_MODEL_DIR
        self.rt_detr = RTDETRModel(self.model_path)
        self.lpr_model = lpr_model
        self.attr_model = VehicleAttributeModelONNX(config.PPVEHICLE_ATTR_ONNX)
        
        self.conf_threshold = 0.4
        
        self.conf_threshold = 0.4
        self._next_track_id = 10000  # Start high
        self._track_history = {}
        self.attr_cache = {}    # track_id -> {ts, data}
        
    def load(self):
        """Load RT-DETR ONNX model"""
        print(f"🚗 Loading PP-Vehicle (ONNX) from {self.model_path}...", flush=True)
        try:
            self.rt_detr.load()
            if self.attr_model: self.attr_model.load()
            print(f"✅ PP-Vehicle (ONNX) Loaded.", flush=True)
        except Exception as e:
            print(f"❌ Failed to load PP-Vehicle (ONNX): {e}", flush=True)

    def predict(self, frames, camera_ids=None):
        """
        Detect vehicles and run LPR on each
        """
        # Ensure list
        if not isinstance(frames, list):
            frames = [frames]
            
        if len(frames) == 0:
            return []
            
        results = []
        
        for i, frame in enumerate(frames):
            result = PPVehicleResult()
            cam_id = camera_ids[i] if camera_ids else f"cam_{i}"
            
            try:
                # 1. Run RT-DETR (ONNX)
                boxes, scores, cls_ids = self.rt_detr.predict(frame)
                
                # 2. Filter & Track
                vehicle_idx = 0
                for j in range(len(boxes)):
                    box = boxes[j]
                    score = scores[j]
                    cls_id = int(cls_ids[j])
                    
                    if cls_id in VEHICLE_CLASSES and score > self.conf_threshold:
                        x1, y1, x2, y2 = box
                        track_id = self._assign_track_id(cam_id, [x1, y1, x2, y2])
                        
                        result.boxes.append([x1, y1, x2, y2])
                        result.id.append(track_id)
                        result.cls.append(cls_id)
                        result.conf.append(float(score))
                        result.vehicle_types[vehicle_idx] = VEHICLE_CLASSES[cls_id]
                        # 3. Run LPR on vehicle crop
                        # Note: LPR model handles RGB to BGR conversion internally
                        if self.lpr_model:
                            x1i, y1i, x2i, y2i = map(int, [x1, y1, x2, y2])
                            h, w = frame.shape[:2]
                            x1i = max(0, min(x1i, w))
                            x2i = max(0, min(x2i, w))
                            y1i = max(0, min(y1i, h))
                            y2i = max(0, min(y2i, h))
                            
                            if (x2i - x1i) > 50 and (y2i - y1i) > 50:  # Min 50px for better OCR
                                crop = frame[y1i:y2i, x1i:x2i]
                                lpr_result = self.lpr_model.predict(crop)
                                if lpr_result.label:
                                    print(f"📍 PP-Vehicle Plate: {lpr_result.label}", flush=True)
                                    result.plates[vehicle_idx] = lpr_result.label
                                    
                                    result.plates[vehicle_idx] = lpr_result.label
                                    
                        # 4. Vehicle Attributes
                        if self.attr_model:
                             current_time = time.time()
                             if track_id in self.attr_cache and (current_time - self.attr_cache[track_id]['ts']) < 2.0:
                                 result.attributes[vehicle_idx] = self.attr_cache[track_id]['data']
                             else:
                                 # Logic: only run on large enough crops or if desired
                                 crop_attr = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
                                 if crop_attr.size > 0:
                                     attrs = self.attr_model.predict(frame, [[x1,y1,x2,y2]]) # Batch of 1
                                     if attrs:
                                         result.attributes[vehicle_idx] = attrs[0]
                                         self.attr_cache[track_id] = {'ts': current_time, 'data': attrs[0]}
                                     
                        vehicle_idx += 1
                        
            except Exception as e:
                print(f"❌ PP-Vehicle inference error: {e}", flush=True)
                # import traceback
                # traceback.print_exc()
                
            results.append(result)
            
        return results
        
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
