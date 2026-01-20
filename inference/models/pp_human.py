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
from .attributes_onnx import AttributesModelONNX
from .action_onnx import ActionModelONNX
from .reid_onnx import ReIDModelONNX
from collections import deque
import time

# COCO class IDs for person detection
PERSON_CLASS_ID = 0

class PPHumanResult:
    """Result container"""
    def __init__(self):
        self.boxes = []
        self.id = []
        self.cls = []
        self.conf = []
        self.attributes = {} # id -> attr dict
        self.actions = {}    # id -> (action_label, score)
        self.reid = {}       # id -> embedding_vector
        
def action_scan_threshold(label, score):
    # Thresholds for specific actions
    if label == "falling": return score > 0.6
    if label == "fighting": return score > 0.5
    return score > 0.5


class PPHumanModel:
    """
    PP-Human: Detection + Attributes + Pose/Action + ReID
    """
    def __init__(self, model_dir=None):
        # Detection Model
        self.det_model = RTDETRModel(model_path=config.PPHUMAN_DET_MODEL_DIR)
        
        self.conf_threshold = 0.5
        self._next_track_id = 0
        self._track_history = {}  # Simple IOU-based tracking
        
        # Sub-models
        self.pose_model = PoseModel(model_path=config.PPHUMAN_POSE_MODEL_DIR)
        self.attr_model = AttributesModelONNX(model_path=config.PPHUMAN_ATTR_ONNX)
        self.action_model = ActionModelONNX(model_path=config.PPHUMAN_ACTION_ONNX)
        self.reid_model = ReIDModelONNX(model_path=config.PPHUMAN_REID_ONNX)
        
        self.ACTION_WINDOW_SIZE = 50
        
        # Action Recognition State
        self.action_buffers = {} # {track_id: deque}
        self.attr_cache = {}     # track_id -> {ts, data}
        self.reid_cache = {}     # track_id -> {ts, data}
        # Optimization State
        self.mog2 = {} # cam_id -> background subtractor
        self.SKIP_FRAMES = 2 # Process 1 out of 3 frames (0, 1, 2 skipped?? No, run 0, skip 1, 2)
        self.frame_counters = {} # cam_id -> int

    def load(self):
        """Load RT-DETR model ONLY. Sub-models are Lazy Loaded."""
        try:
            print("🚀 Loading PP-Human Pipeline (Detection Only)...", flush=True)
            self.det_model.load()
            
            # LAZY LOADING: Do NOT load sub-models here.
            # They will be loaded on-demand in predict()
            # self.pose_model.load()
            # self.attr_model.load()
            # self.action_model.load()
            # self.reid_model.load()
            
            print("✅ PP-Human Detection Loaded (Sub-models: Lazy).", flush=True)
        except Exception as e:
            print(f"❌ Failed to load PP-Human: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def _ensure_loaded(self, model, name):
        """Lazy Load Helper"""
        # Specific check for our model wrappers
        # Most of them use self.session = None initially
        if hasattr(model, 'session') and model.session is None:
             print(f"⚡ BOOM! Lazy Loading {name} Model...", flush=True)
             try:
                 model.load()
                 print(f"✅ {name} Loaded.", flush=True)
             except Exception as e:
                 print(f"❌ Failed to Lazy Load {name}: {e}", flush=True)

    def _check_motion(self, frame, cam_id):
        """Returns True if motion detected"""
        if cam_id not in self.mog2:
            self.mog2[cam_id] = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=16, detectShadows=False)
        
        # Downscale for speed
        small_frame = cv2.resize(frame, (320, 180))
        fgmask = self.mog2[cam_id].apply(small_frame)
        
        # Count non-zero
        count = np.count_nonzero(fgmask)
        ratio = count / (320 * 180)
        return ratio > 0.01 # 1% movement

    def predict(self, frame_or_batch, camera_ids=None, camera_configs=None):
        """
        Run detection on a batch of frames
        """
        frames = frame_or_batch if isinstance(frame_or_batch, list) else [frame_or_batch]
        
        # Handle camera_ids
        cam_ids_list = []
        if camera_ids:
            if isinstance(camera_ids, list): 
                cam_ids_list = camera_ids
            else: 
                cam_ids_list = [camera_ids] * len(frames)
        else:
            cam_ids_list = ["cam_0"] * len(frames)
        
        # Handle camera_configs
        configs_list = camera_configs if camera_configs else [{}] * len(frames)
            
        results_list = []
        
        # --- Pre-filter: Identify frames to skip ---
        frames_to_process = []
        indices_to_process = []
        
        # Collect Global Feature Needs for this Batch (for Lazy Loading)
        batch_needs_pose = False
        batch_needs_attr = False
        batch_needs_reid = False
        
        for i, frame in enumerate(frames):
            cam_id = cam_ids_list[i]
            cfg = configs_list[i]
            feats = cfg.get("features", [])
            
            # Check features needed
            if any(f in feats for f in ["fight_detection", "fall_detection", "compliance_smoking", "compliance_calling"]):
                batch_needs_pose = True
            if "human_attr" in feats:
                batch_needs_attr = True
            if "human_reid" in feats:
                batch_needs_reid = True

            # 1. Skip Logic (Round Robin)
            if cam_id not in self.frame_counters: self.frame_counters[cam_id] = 0
            self.frame_counters[cam_id] += 1
            
            should_process = (self.frame_counters[cam_id] % (self.SKIP_FRAMES + 1) == 0)
            
            # 2. MOG2 Logic
            has_active = len(self._track_history.get(cam_id, {})) > 0
            has_motion = self._check_motion(frame, cam_id)
            
            if not has_motion and not has_active:
                should_process = False
                
            if should_process:
                frames_to_process.append(frame)
                indices_to_process.append(i)
            else:
                results_list.append(PPHumanResult()) # Empty

        final_results = [PPHumanResult() for _ in range(len(frames))] # Default empty
        
        # --- LAZY LOADING TRIGGER ---
        if batch_needs_pose:
            self._ensure_loaded(self.pose_model, "Pose")
            self._ensure_loaded(self.action_model, "Action")
        if batch_needs_attr:
            self._ensure_loaded(self.attr_model, "Attributes")
        if batch_needs_reid:
            self._ensure_loaded(self.reid_model, "ReID")
        
        if frames_to_process:
            try:
                # Optimized Batch
                # print(f"🔄 DEBUG: PPHuman Batch {len(frames_to_process)}/{len(frames)}", flush=True)
                all_detections = self.det_model.predict_batch(frames_to_process)
                
                det_idx = 0
                for global_idx in indices_to_process:
                    boxes, scores, classes = all_detections[det_idx]
                    det_idx += 1
                    
                    frame = frames[global_idx]
                    cam_id = cam_ids_list[global_idx]
                    config = configs_list[global_idx]
                    
                    result = final_results[global_idx] # The object to populate
                    
                    person_boxes = []
                    
                    # Filter and Assign Tracks
                    for k, (box, score, cls_id) in enumerate(zip(boxes, scores, classes)):
                        cls_id = int(cls_id)
                        
                        # New PP-YOLOE-s Mapping: 0=Person, 1=Car, 2=Moto
                        is_valid_cls = (cls_id == 0 or cls_id in [1, 2, 3, 5, 7])
                        
                        if is_valid_cls and score > 0.4: # Higher threshold when optimizing
                            x1, y1, x2, y2 = box
                            
                            track_id = self._assign_track_id(cam_id, [x1, y1, x2, y2])
                            
                            result.boxes.append([x1, y1, x2, y2])
                            result.id.append(track_id)
                            result.cls.append(int(cls_id))
                            result.conf.append(float(score))
                            
                            if cls_id == 0:
                               person_boxes.append([x1, y1, x2, y2])
                    
                    current_time = time.time()
                    features = config.get("features", []) if config else []
                    
                    # 2. Pose Estimation - Checked against loaded model
                    needs_pose = any(f in features for f in ["fight_detection", "fall_detection"])
                    
                    if needs_pose and person_boxes and self.pose_model.session:
                         try:
                            pose_results = self.pose_model.predict([frame], [person_boxes])
                            kpts = pose_results[0] if pose_results else []
                            
                            # Map kpts to track_ids
                            if kpts:
                                for idx, kp in enumerate(kpts):
                                    if idx < len(result.id) and result.cls[idx] == 0:
                                        track_id = result.id[idx]
                                        
                                        # Buffer logic for Action
                                        if track_id not in self.action_buffers:
                                            self.action_buffers[track_id] = deque(maxlen=self.ACTION_WINDOW_SIZE)
                                        self.action_buffers[track_id].append(kp) # kp is (17, 3)
                                        
                                        # Run Action Inference if buffer sufficient
                                        if len(self.action_buffers[track_id]) >= self.ACTION_WINDOW_SIZE and self.action_model.session:
                                            action_label, action_score = self.action_model.predict(list(self.action_buffers[track_id]))
                                            if action_label and action_scan_threshold(action_label, action_score):
                                                 result.actions[track_id] = (action_label, action_score)
                                    
                         except Exception as pe:
                            print(f"Pose/Action Error: {pe}", flush=True)

                    
                    # 3. Attributes - Checked against loaded model & Camera Config
                    needs_attr = "human_attr" in features
                    # NOTE: We use Camera Config 'features', NOT global config anymore for switching.
                    
                    if needs_attr and person_boxes and self.attr_model.session:
                         p_idx = 0
                         batch_boxes = []
                         batch_ids = []
                         for i, cls_id in enumerate(result.cls):
                             if cls_id == 0:
                                 tid = result.id[i]
                                 # 5.0s Cache!
                                 if tid in self.attr_cache and (current_time - self.attr_cache[tid]['ts']) < 5.0:
                                     result.attributes[tid] = self.attr_cache[tid]['data']
                                 else:
                                     batch_boxes.append(person_boxes[p_idx])
                                     batch_ids.append(tid)
                                 p_idx += 1
                         if batch_boxes:
                             try:
                                 batch_crops = []
                                 h, w = frame.shape[:2]
                                 for box in batch_boxes:
                                     x1, y1, x2, y2 = map(int, box[:4])
                                     x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
                                     batch_crops.append(frame[y1:y2, x1:x2])
                                 attr_results = self.attr_model.predict(batch_crops)
                                 for b_id, attrs in zip(batch_ids, attr_results):
                                     if attrs:
                                         # print(f"🧬 Attr Calc for {b_id}: {attrs}", flush=True) 
                                         result.attributes[b_id] = attrs
                                         self.attr_cache[b_id] = {'ts': current_time, 'data': attrs}
                             except Exception as ae:
                                 # print(f"Attr Error: {ae}", flush=True)
                                 pass

                    # 4. ReID Integration (Throttled)
                    needs_reid = "human_reid" in features
                    if needs_reid and person_boxes and self.reid_model.session:
                         p_idx = 0
                         batch_boxes = []
                         batch_ids = []
                         
                         for i, cls_id in enumerate(result.cls):
                             if cls_id == 0:
                                 tid = result.id[i]
                                 if tid in self.reid_cache and (current_time - self.reid_cache[tid]['ts']) < 2.0: # 2s Cache ReID
                                     result.reid[tid] = self.reid_cache[tid]['data']
                                 else:
                                     batch_boxes.append(person_boxes[p_idx])
                                     batch_ids.append(tid)
                                 p_idx += 1
                                 
                         if batch_boxes:
                             try:
                                reids = self.reid_model.predict(frame, batch_boxes)
                                for b_id, emb in zip(batch_ids, reids):
                                     if emb is not None:
                                         result.reid[b_id] = emb
                                         self.reid_cache[b_id] = {'ts': current_time, 'data': emb}
                             except Exception as re:
                                print(f"ReID Error: {re}", flush=True)

            except Exception as e:
                print(f"❌ Pipeline error: {e}", flush=True)
                
        return final_results

    def _assign_track_id(self, camera_id, box, iou_threshold=0.5):
        """Simple IOU Tracker - with Cleanup"""
        if camera_id not in self._track_history: self._track_history[camera_id] = {}
        
        # Cleanup old tracks (optional, but good for memory)
        # For now keep simple
        
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

def action_scan_threshold(label, score):
    if score < 0.6: return False
    return True
