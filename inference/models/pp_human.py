"""
PP-Human Model - RT-DETR Implementation (ONNX)
Uses RT-DETR-R18 for human detection via ONNXRuntime.
"""
import os
import cv2
import numpy as np
import time
from ..config import config

# Import new ONNX Wrapper
from .detection import RTDETRModel 
from .pose import PoseModel
from .action import ActionModel

# COCO class IDs for person detection
PERSON_CLASS_ID = 0

class PPHumanResult:
    """Result container for human detection"""
    def __init__(self):
        self.boxes = []      # [[x1,y1,x2,y2], ...]
        self.id = []         # [track_id, ...]
        self.cls = []        # [class_id, ...]
        self.conf = []       # [score, ...]
        self.actions = {}    # {track_id: action_label}
        self.attributes = {} # {track_id: {attr_name: value}}

class PPHumanModel:
    """
    Human Detection using RT-DETR-R18 (ONNX)
    Integrates:
    1. RT-DETR (Detection) -> ONNX
    2. ByteTrack (Tracking) -> IOU simple
    3. RTMPose (Skeleton) -> ONNX
    4. ST-GCN (Action) -> Placeholder
    """
    
    def __init__(self):
        # Detection Model
        self.det_model = RTDETRModel(model_path=config.PPHUMAN_DET_MODEL_DIR)
        
        self.conf_threshold = 0.5
        self._next_track_id = 0
        self._track_history = {}  # Simple IOU-based tracking
        
        # Sub-models
        self.pose_model = PoseModel()
        self.action_model = ActionModel()
        
        # Action Recognition State
        self._keypoint_buffer = {} # {track_id: deque}
        self.ACTION_WINDOW_SIZE = 50 

    def load(self):
        """Load RT-DETR model and Sub-models"""
        try:
            print("🚀 Loading PP-Human Pipeline (ONNX)...", flush=True)
            
            # Load Detection (ONNX)
            self.det_model.load()
                
            # Load Sub-models
            self.pose_model.load()
            self.action_model.load() 
            
            print("✅ PP-Human Pipeline Loaded!", flush=True)
            
        except Exception as e:
            print(f"❌ Failed to load models: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def predict(self, frame, camera_ids=None):
        """
        Run detection + Pose + Action on a single frame
        Returns: [PPHumanResult]
        """
        # Support batch of 1 for compatibility
        if isinstance(frame, list):
            frame = frame[0]
            
        # Handle camera_ids (if single frame, explicit id or default)
        cam_id = "cam_0"
        if camera_ids:
            if isinstance(camera_ids, list): cam_id = camera_ids[0]
            else: cam_id = camera_ids
            
        result = PPHumanResult()
        
        try:
            # 1. Detection (RT-DETR ONNX)
            boxes, scores, classes = self.det_model.predict(frame)
            
            person_boxes = []
            
            # Filter and Assign Tracks
            for i, (box, score, cls_id) in enumerate(zip(boxes, scores, classes)):
                if int(cls_id) == PERSON_CLASS_ID and score > self.conf_threshold:
                    x1, y1, x2, y2 = box
                    # Ensure coordinates are within image bounds?
                    
                    track_id = self._assign_track_id(cam_id, [x1, y1, x2, y2])
                    
                    result.boxes.append([x1, y1, x2, y2])
                    result.id.append(track_id)
                    result.cls.append(int(cls_id))
                    result.conf.append(float(score))
                    
                    person_boxes.append([x1, y1, x2, y2])
            
            # 2. Pose Estimation
            if person_boxes:
                # PoseModel.predict expects list of frames and list of box-lists
                pose_results = self.pose_model.predict([frame], [person_boxes])
                frame_keypoints = pose_results[0] if pose_results else []
                
                # 3. Action Logic (Placeholder)
                pass

        except Exception as e:
            print(f"❌ Pipeline error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            
        return [result]

    def _assign_track_id(self, camera_id, box, iou_threshold=0.5):
        """Simple IOU Tracker"""
        if camera_id not in self._track_history: self._track_history[camera_id] = {}
        best_match, best_iou = None, 0.0
        
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
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - inter
        return inter / union if union > 0 else 0
