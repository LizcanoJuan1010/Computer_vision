import os
import cv2
import yaml
import numpy as np
import paddle
from ..config import config

import builtins
import sys

# SYSTEM FIX: Patch deploy.python.infer to avoid NameError: name 'FLAGS' is not defined
# The PaddleDetection library uses a global FLAGS variable. We inject it directly into builtins.
class MockFlags:
    def __getattr__(self, name):
        if name == "collect_trt_shape_info": return False
        if name == "tuned_trt_shape_file": return "tuned_trt_shape.pbtxt"
        if name == "device": return "GPU"
        if name == "use_gpu": return True 
        if name == "prog_file": return "" # Return empty string to avoid stat(None)
        if name == "params_file": return "" # Return empty string to avoid stat(None)
        if name == "model_dir": return "." # Return valid path
        if name == "use_fd_format": return False
        if name == "run_benchmark": return False
        if name == "run_mode": return "paddle"
        return "" # Return empty string to act as False but satisfy path requirements
        
mock_flags = MockFlags()
builtins.FLAGS = mock_flags
print("DEBUG: Injected global builtins.FLAGS", flush=True)

try:
    # Try importing from the cloned PaddleDetection repo (in Docker PYTHONPATH)
    from deploy.pipeline.pipeline import Pipeline, PipePredictor
    from deploy.python.infer import Detector
    from ppdet.core.workspace import load_config
    # Utils for manual pipeline
    from deploy.pipeline.pipe_utils import parse_mot_res, crop_image_with_mot

    # SYSTEM FIX: Monkeypatch create_predictor to disable IR Optimization
    try:
        import deploy.python.infer as infer_mod
        if hasattr(infer_mod, 'create_predictor'):
            _orig_create_predictor = infer_mod.create_predictor
            def _patched_create_predictor(opt_config):
                print("DEBUG: Patched create_predictor called. Disabling IR Optim.", flush=True)
                if hasattr(opt_config, 'switch_ir_optim'):
                    opt_config.switch_ir_optim(False)
                return _orig_create_predictor(opt_config)
            infer_mod.create_predictor = _patched_create_predictor
            print("DEBUG: Successfully patched infer_mod.create_predictor", flush=True)
    except Exception as e:
        print(f"DEBUG: Failed to patch create_predictor: {e}", flush=True)
    
    PP_HUMAN_AVAILABLE = True

except ImportError as e:
    print(f"Warning: PaddleDetection 'deploy.pipeline' not found. Running in STUB mode. Error: {e}")
    PP_HUMAN_AVAILABLE = False

class PPHumanModel:
    def __init__(self):
        self.pipeline = None
        self.cfg_path = "/app/inference/config/pphuman.yaml" # Default container path

    def load(self):
        if not PP_HUMAN_AVAILABLE:
            print("⚠️ PPHumanModel: STUB Mode Active. PaddleDetection not found. Real model will NOT run.", flush=True)
            return

        print(f"Loading PP-Human Pipeline from {self.cfg_path}...", flush=True)
        
        # Check if config exists
        if not os.path.exists(self.cfg_path):
             # Fallback for local testing if path differs
             if os.path.exists("inference/config/pphuman.yaml"):
                 self.cfg_path = "inference/config/pphuman.yaml"
        
        # Initialize Pipeline
        try:
            # Load config
            if PP_HUMAN_AVAILABLE:
                self.cfg = load_config(self.cfg_path)
                # Inject defaults expected by Pipeline
                if 'visual' not in self.cfg: self.cfg['visual'] = False
                if 'crop_thresh' not in self.cfg: self.cfg['crop_thresh'] = 0.5
                if 'kpt_thresh' not in self.cfg: self.cfg['kpt_thresh'] = 0.5
                
                # VIDEO_ACTION fixes (short_size)
                if 'VIDEO_ACTION' in self.cfg:
                    if isinstance(self.cfg['VIDEO_ACTION'], dict):
                        self.cfg['VIDEO_ACTION']['enable'] = True
                        if 'short_size' not in self.cfg['VIDEO_ACTION']:
                            self.cfg['VIDEO_ACTION']['short_size'] = 256
                        if 'target_size' not in self.cfg['VIDEO_ACTION']:
                            self.cfg['VIDEO_ACTION']['target_size'] = 224
                        if 'batch_size' not in self.cfg['VIDEO_ACTION']:
                             self.cfg['VIDEO_ACTION']['batch_size'] = 1
                
                # Fix KeyError: 'enable' in Pipeline init
                if 'ATTR' in self.cfg and 'enable' not in self.cfg['ATTR']:
                    self.cfg['ATTR']['enable'] = False
                
                if 'warmup_frame' not in self.cfg:
                    self.cfg['warmup_frame'] = 50
                
                # Fix KeyError: 'KPT' (Required by SKELETON_ACTION)
                if 'KPT' not in self.cfg:
                    self.cfg['KPT'] = {
                        'model_dir': '/app/inference/weights/dark_hrnet_w32_256x192',
                        'batch_size': 1
                    }
                
                # Fix KeyError: 'MOT' (Pipeline likely expects MOT for tracking)
                if 'MOT' not in self.cfg and 'DET' in self.cfg:
                    self.cfg['MOT'] = self.cfg['DET'].copy()
                    self.cfg['MOT']['enable'] = True
                    self.cfg['MOT']['tracker_config'] = '/app/inference/config/tracker.yaml'
                
                # SKELETON_ACTION fixes
                if 'SKELETON_ACTION' in self.cfg:
                     if isinstance(self.cfg['SKELETON_ACTION'], dict):
                         kpt_path = self.cfg.get('KPT', {}).get('model_dir', '/app/inference/weights/dark_hrnet_w32_256x192')
                         if os.path.exists(kpt_path):
                             self.cfg['SKELETON_ACTION']['enable'] = True
                             if 'batch_size' not in self.cfg['SKELETON_ACTION']:
                                  self.cfg['SKELETON_ACTION']['batch_size'] = 1
                         else:
                             self.cfg['SKELETON_ACTION']['enable'] = False
                
                # ID Based fixes
                if 'ID_BASED_DETACTION' in self.cfg:
                     if isinstance(self.cfg['ID_BASED_DETACTION'], dict):
                         self.cfg['ID_BASED_DETACTION']['enable'] = True
                         if 'batch_size' not in self.cfg['ID_BASED_DETACTION']:
                             self.cfg['ID_BASED_DETACTION']['batch_size'] = 1
                 
                if 'ID_BASED_CLSACTION' in self.cfg:
                     if isinstance(self.cfg['ID_BASED_CLSACTION'], dict):
                         self.cfg['ID_BASED_CLSACTION']['enable'] = True
                         if 'batch_size' not in self.cfg['ID_BASED_CLSACTION']:
                             self.cfg['ID_BASED_CLSACTION']['batch_size'] = 1
                
                # Threshold Overrides (Lower for better recall)
                if 'DET' in self.cfg:
                     self.cfg['DET']['threshold'] = 0.2
                if 'MOT' in self.cfg:
                     self.cfg['MOT']['threshold'] = 0.2

            # Create dummy args
            class Args:
                def __init__(self):
                    self.device = 'gpu' if paddle.is_compiled_with_cuda() else 'cpu'
                    self.output_dir = None
                    self.run_benchmark = False
                    self.enable_mkldnn = False
                    self.cpu_threads = 1
                    self.enable_ce = False
                    self.image_file = None
                    self.image_dir = None
                    self.video_file = None
                    self.video_dir = None
                    self.rtsp = ['rtsp://127.0.0.1:8554/mock'] # Bypass "Illegal Input" check
                    self.camera_id = -1
                    self.draw_center_traj = False
                    self.secs_interval = 10
                    self.do_entrance_counting = False
                    self.do_break_in_counting = False
                    self.region_type = "horizontal"
                    self.illegal_parking_time = -1
                    self.run_mode = 'paddle' # Force native Paddle inference
                    self.trt_min_shape = 1
                    self.trt_max_shape = 1280
                    self.trt_opt_shape = 640
                    self.trt_calib_mode = False
                
                def __getattr__(self, name):
                    return None
            
            args = Args()
            print(f"ℹ️ PPHuman Configured Device: {args.device.upper()}", flush=True)

            print("DEBUG: Pipeline init started", flush=True)
            try:
                self.pipeline = Pipeline(args, self.cfg)
                self.pipeline.cfg = self.cfg
            except Exception as e:
                print(f"⚠️ Pipeline Init Error: {e}")
                raise e
            print("✅ PP-Human: Pipeline initialized successfully.", flush=True)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"❌ Error initializing PP-Human Pipeline: {e}", flush=True)
            self.pipeline = None

    def predict(self, frame_or_batch, camera_ids=None, conf=0.5):
        """
        Run PP-Human detection on frames.
        Uses the native MOT predictor API which handles all preprocessing internally.
        Expects RGB input (from main.py), converts to BGR for PaddleDetection.
        """
        frames = frame_or_batch if isinstance(frame_or_batch, list) else [frame_or_batch]
        results = []
        
        # Handle Stub Mode
        if not self.pipeline:
            print("⚠️ PPHuman predict called but model is STUB.", flush=True)
            for _ in frames:
                results.append(PPHumanResult())
            return results

        if not hasattr(self, 'frame_id'):
            self.frame_id = 0

        predictor = self.pipeline.predictor
        if isinstance(predictor, list):
            predictor = predictor[0]

        mot_predictor_obj = predictor.mot_predictor 
        
        batch_size = len(frames)
        
        for i in range(batch_size):
            self.frame_id += 1
            res = PPHumanResult()
            
            frame = frames[i]
            cam_id = camera_ids[i] if (camera_ids and i < len(camera_ids)) else f"global_{i}"
            
            try:
                # Convert RGB to BGR (PaddleDetection expects BGR!)
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                
                # Call MOT predictor's predict_image
                mot_res = mot_predictor_obj.predict_image([frame_bgr], visual=False)
                
                # Debug what we got
                # The MOT predictor returns: [results] where results is:
                # [bboxes_dict, scores_dict, track_ids_dict]
                # bboxes_dict: {class_id: [[x,y,w,h], ...]}
                # scores_dict: {class_id: [score, ...]}
                # track_ids_dict: {class_id: [tid, ...]}
                
                if len(mot_res) > 0 and isinstance(mot_res[0], list) and len(mot_res[0]) >= 3:
                    bboxes_dict = mot_res[0][0]
                    scores_dict = mot_res[0][1]
                    track_ids_dict = mot_res[0][2]
                    
                    for cls_id in bboxes_dict.keys():
                        bboxes = bboxes_dict[cls_id]
                        scores = scores_dict.get(cls_id, [0.9] * len(bboxes))
                        track_ids = track_ids_dict.get(cls_id, list(range(len(bboxes))))
                        
                        for idx, bbox in enumerate(bboxes):
                            if len(bbox) >= 4:
                                x, y, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
                                x1, y1, x2, y2 = x, y, x + w, y + h
                                
                                score = scores[idx] if idx < len(scores) else 0.9
                                tid = track_ids[idx] if idx < len(track_ids) else len(res.id)
                                
                                if score > 0.10:  # Filter low confidence (Lowered further)
                                    res.id.append(int(tid))
                                    res.cls.append(int(cls_id))
                                    res.conf.append(float(score))
                                    res.boxes.append([x1, y1, x2, y2])
                    
                    if len(res.boxes) > 0:
                        print(f"[{cam_id}] Detectados: {len(res.boxes)} personas", flush=True)
                    
            except Exception as e:
                import traceback
                print(f"❌ PPHuman Prediction Error: {e}", flush=True)
                traceback.print_exc()
            
            results.append(res)
        
        return results


class PPHumanResult:
    def __init__(self):
        self.boxes = []  # [x1, y1, x2, y2]
        self.conf = []
        self.cls = []
        self.id = []  # Track IDs
        
        # Extended Metadata
        self.attributes = {}  # {idx: {"gender": "Male", ...}}
        self.actions = {}     # {idx: "fighting"}
        self.reid_features = {} # {track_id: np.array} (ReID Embeddings)
        self.global_events = [] # ["fight_detection"] (Frame-level events)
