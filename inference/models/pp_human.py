import os
import cv2
import yaml
import numpy as np
import paddle

try:
    # Try importing from the cloned PaddleDetection repo (in Docker PYTHONPATH)
    from deploy.pipeline.pipeline import Pipeline, PipePredictor
    from deploy.python.infer import Detector
    from ppdet.core.workspace import load_config
    # Utils for manual pipeline
    from deploy.pipeline.pipe_utils import parse_mot_res, crop_image_with_mot
    
    PP_HUMAN_AVAILABLE = True
except ImportError:
    print("Warning: PaddleDetection 'deploy.pipeline' not found. Running in STUB mode.")
    PP_HUMAN_AVAILABLE = False

class PPHumanModel:
    def __init__(self):
        self.pipeline = None
        self.cfg_path = "/app/inference/config/pphuman.yaml" # Default container path

    def load(self):
        if not PP_HUMAN_AVAILABLE:
            print("PPHumanModel: Stub loaded (Real PaddleDetection not found).")
            return

        print(f"Loading PP-Human Pipeline from {self.cfg_path}...")
        
        # Check if config exists
        if not os.path.exists(self.cfg_path):
             # Fallback for local testing if path differs
             if os.path.exists("inference/config/pphuman.yaml"):
                 self.cfg_path = "inference/config/pphuman.yaml"
        
        # Initialize Pipeline
        # We need to mimic the 'args' or 'cfg' structure expected by Pipeline.__init__
        # Usually Pipeline(args, cfg)
        try:
            # Load config
            # We use load_config from ppdet to parse the yaml including includes
            if PP_HUMAN_AVAILABLE:
                self.cfg = load_config(self.cfg_path)
                # Inject defaults expected by Pipeline
                if 'visual' not in self.cfg: self.cfg['visual'] = False
                if 'crop_thresh' not in self.cfg: self.cfg['crop_thresh'] = 0.5
                if 'kpt_thresh' not in self.cfg: self.cfg['kpt_thresh'] = 0.5
                
                # Fix KeyError: 'enable' in Pipeline init
                if 'ATTR' in self.cfg and 'enable' not in self.cfg['ATTR']:
                    print("DEBUG: Injecting default ATTR['enable'] = False", flush=True)
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
                    print("DEBUG: Aliasing DET config to MOT", flush=True)
                    self.cfg['MOT'] = self.cfg['DET'].copy()
                    # Ensure enable is set if needed (though usually implied)
                    self.cfg['MOT']['enable'] = True
                    self.cfg['MOT']['tracker_config'] = '/app/inference/config/tracker.yaml'
                
                # SKELETON_ACTION fixes
                if 'SKELETON_ACTION' in self.cfg:
                     if isinstance(self.cfg['SKELETON_ACTION'], dict):
                         # Check if KPT model exists
                         # Check if KPT model exists
                         kpt_path = self.cfg.get('KPT', {}).get('model_dir', '/app/inference/weights/dark_hrnet_w32_256x192')
                         if os.path.exists(kpt_path):
                             self.cfg['SKELETON_ACTION']['enable'] = True
                             if 'batch_size' not in self.cfg['SKELETON_ACTION']:
                                  self.cfg['SKELETON_ACTION']['batch_size'] = 1
                         else:
                             print(f"WARNING: KPT model not found at {kpt_path}. Disabling SKELETON_ACTION.", flush=True)
                             self.cfg['SKELETON_ACTION']['enable'] = False
                
                # ID Based fixes
                if 'ID_BASED_DETACTION' in self.cfg: # Smoking usually
                     if isinstance(self.cfg['ID_BASED_DETACTION'], dict):
                         self.cfg['ID_BASED_DETACTION']['enable'] = True
                         if 'batch_size' not in self.cfg['ID_BASED_DETACTION']:
                             self.cfg['ID_BASED_DETACTION']['batch_size'] = 1
                 
                if 'ID_BASED_CLSACTION' in self.cfg: # Calling usually
                     if isinstance(self.cfg['ID_BASED_CLSACTION'], dict):
                         self.cfg['ID_BASED_CLSACTION']['enable'] = True
                         if 'batch_size' not in self.cfg['ID_BASED_CLSACTION']:
                             self.cfg['ID_BASED_CLSACTION']['batch_size'] = 1
                
                # Threshold Overrides
                # Threshold Overrides (User requested lower confidence)
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
                    self.video_file = None # Also commonly used
                    self.video_dir = None # Added based on logs
                    self.rtsp = ['rtsp://127.0.0.1:8554/mock'] # Bypass "Illegal Input" check
                    self.camera_id = -1
                    # New attributes for PipePredictor validation
                    self.draw_center_traj = False
                    self.secs_interval = 10
                    self.do_entrance_counting = False
                    self.do_break_in_counting = False
                    self.do_break_in_counting = False
                    self.region_type = "horizontal" # or vertical
                    self.region_polygon = []
                    self.illegal_parking_time = -1
                    
                    # Inference options
                    self.device = 'gpu'
                    self.run_mode = 'paddle'
                    self.trt_min_shape = 1
                    self.trt_max_shape = 1280
                    self.trt_opt_shape = 640
                    self.trt_calib_mode = False
                    self.cpu_threads = 1
                    self.enable_mkldnn = False
                
                def __getattr__(self, name):
                    # Fallback for any other missing arg to avoid AttributeError
                    return None
            
            args = Args()

            print("DEBUG: Pipeline init started", flush=True)
            self.pipeline = Pipeline(args, self.cfg)
            self.pipeline.cfg = self.cfg # Explicitly set if Pipeline doesn't
            print("DEBUG: Pipeline init done.", flush=True)
            
            print("PP-Human: Pipeline initialized successfully.", flush=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error initializing PP-Human Pipeline: {e}", flush=True)
            self.pipeline = None

    def predict(self, frame_or_batch, conf=0.5):
        # Handle Stub Mode
        if not self.pipeline:
             # Stub result
             results = []
             frames = frame_or_batch if isinstance(frame_or_batch, list) else [frame_or_batch]
             for _ in frames:
                 results.append(PPHumanResult()) # Empty
             return results

        # Manual Pipeline Orchestration
        results = []
        frames = frame_or_batch if isinstance(frame_or_batch, list) else [frame_or_batch]
        
        if not hasattr(self, 'frame_id'):
            self.frame_id = 0
            
        predictor = self.pipeline.predictor
        # If multi-camera enabled in pipeline, predictor is a list. We assume single instance here.
        if isinstance(predictor, list):
             predictor = predictor[0]

        for frame in frames:
            self.frame_id += 1
            res = PPHumanResult()
            
            try:
                # 1. MOT (Detection + Tracking)
                # predict_image(image_list, visual=False, reuse_det_result=False, frame_count=frame_id)
                # Input must be list of frames (numpy)
                import copy
                # DEBUG: Print frame shape
                print(f"DEBUG: Frame shape: {frame.shape}", flush=True)
                
                mot_res_raw = predictor.mot_predictor.predict_image(
                    [copy.deepcopy(frame)],
                    visual=False,
                    reuse_det_result=False,
                    frame_count=self.frame_id
                )
                
                # DEBUG: Inspect raw result
                # print(f"DEBUG: MOT Raw Keys: {mot_res_raw.keys()}", flush=True)
                if 'boxes' in mot_res_raw:
                     if len(mot_res_raw['boxes']) > 0:
                         print(f"DEBUG: MOT Raw Boxes: {len(mot_res_raw['boxes'])} found", flush=True)
                     else:
                         print("DEBUG: MOT Raw Boxes: 0 found", flush=True)
                
                # Parse MOT Result
                # mot_res is a dict with 'boxes' -> [id, cls, score, x1, y1, x2, y2]
                mot_res = parse_mot_res(mot_res_raw)
                
                # Check for detections
                has_detections = False
                if 'boxes' in mot_res and len(mot_res['boxes']) > 0:
                    has_detections = True
                    # print(f"DEBUG: MOT Parsed Boxes: {len(mot_res['boxes'])}", flush=True)

                # Populate PPHumanResult with MOT data
                if 'boxes' in mot_res:
                    for row in mot_res['boxes']:
                        # row: [id, cls, score, x1, y1, x2, y2]
                        if len(row) >= 7:
                            tid = int(row[0])
                            cls_id = int(row[1])
                            score = float(row[2])
                            bbox = row[3:7].tolist()
                            
                            res.id.append(tid)
                            res.cls.append(cls_id)
                            res.conf.append(score)
                            res.boxes.append(bbox)
                
                # 2. Attributes (Optional)
                if predictor.with_human_attr and has_detections:
                    crop_input, new_bboxes, ori_bboxes = crop_image_with_mot(frame, mot_res)
                    attr_res = predictor.attr_predictor.predict_image(crop_input, visual=False)
                    # output is dict {'output': [{'gender':..., 'age':...}, ...]}
                    if 'output' in attr_res:
                        attrs_list = attr_res['output']
                        for i, attr in enumerate(attrs_list):
                            if i < len(res.id):
                                tid = res.id[i]
                                res.attributes[tid] = attr

                # 3. Action (Skeleton)
                if predictor.with_skeleton_action and has_detections:
                    # Keypoint Detection first
                    # Need crop_input from MOT
                    if not 'crop_input' in locals():
                        crop_input, new_bboxes, ori_bboxes = crop_image_with_mot(frame, mot_res)
                        
                    kpt_pred = predictor.kpt_predictor.predict_image(crop_input, visual=False)
                    
                    # Skeleton Action
                    # predict_skeleton_with_mot(mot_res, kpt_pred)
                    skeleton_res = predictor.skeleton_action_predictor.predict_skeleton_with_mot(mot_res, kpt_pred)
                    
                    # Parse Action Result
                    # skeleton_res is usually list of dicts or similar. 
                    # Need to verify format. Assuming standard list of {track_id, class, ...}
                    # Actually pipeline updates 'action' in result.
                    # Let's inspect 'skeleton_res'.
                    # It usually returns a list of actions associated with tracks.
                    if isinstance(skeleton_res, list):
                        for act in skeleton_res:
                            tid = act.get('track_id')
                            cls = act.get('class', -1)
                            # 0: Falling, 1: Fighting (Default)
                            action_name = "unknown"
                            if cls == 0: action_name = "falling"
                            elif cls == 1: action_name = "fighting"
                            
                            if tid is not None:
                                res.actions[tid] = action_name

                # 4. Action (Detection based - Smoking)
                if getattr(predictor, 'with_idbased_detaction', False) and has_detections:
                     if not 'crop_input' in locals():
                        crop_input, new_bboxes, ori_bboxes = crop_image_with_mot(frame, mot_res)
                     
                     det_action_res = predictor.det_action_predictor.predict(crop_input, mot_res)
                     if isinstance(det_action_res, list):
                         for act in det_action_res:
                             tid = act.get('track_id')
                             label = act.get('label') # e.g. "smoking"
                             if tid is not None and label:
                                 res.actions[tid] = label

                # 5. Action (Classification based - Calling)
                # Time-based threshold logic (10 PM - 5 AM)
                from datetime import datetime
                now = datetime.now()
                night_mode = (now.hour >= 22 or now.hour < 5)
                call_threshold = 0.4 if night_mode else 0.8
                
                if getattr(predictor, 'with_idbased_clsaction', False) and has_detections:
                     # Dynamically update threshold if supported
                     if hasattr(predictor, 'cls_action_predictor'):
                         if hasattr(predictor.cls_action_predictor, 'threshold'):
                             predictor.cls_action_predictor.threshold = call_threshold
                             
                     if not 'crop_input' in locals():
                        crop_input, new_bboxes, ori_bboxes = crop_image_with_mot(frame, mot_res)
                     
                     # Predict
                     cls_action_res = predictor.cls_action_predictor.predict(crop_input, mot_res)
                     
                     if isinstance(cls_action_res, list):
                         for act in cls_action_res:
                             tid = act.get('track_id')
                             label = act.get('label') # e.g. "calling"
                             score = act.get('score', 0.0) # Check score against our manual threshold if needed? 
                             # Predictor usually filters by its internal threshold.
                             
                             if tid is not None and label:
                                 # Optional: Manual double check if internal threshold update failed
                                 # if score >= call_threshold:
                                 res.actions[tid] = label

            except Exception as e:
                print(f"PP-Human Prediction Error: {e}")
                import traceback
                traceback.print_exc()
            
            results.append(res)
            
        return results

    def _parse_result(self, raw_res):
        # Convert Paddle Pipeline dict to PPHumanResult
        res = PPHumanResult()
        
        # 1. Detection/Tracking (res['boxes'] or res['res'])
        # 'boxes': [class, score, x1, y1, x2, y2]
        # 'res': [track_id, class, score, x1, y1, x2, y2] (MOT)
        
        boxes_data = raw_res.get('boxes')
        mot_data = raw_res.get('res')
        
        if mot_data is not None and len(mot_data) > 0:
            # MOT Format
            # [track_id, class, score, x1, y1, x2, y2]
            mot_arr = np.array(mot_data)
            for row in mot_arr:
                if len(row) >= 7:
                    tid = int(row[0])
                    cls_id = int(row[1])
                    score = float(row[2])
                    bbox = row[3:7].tolist() # [x1, y1, x2, y2]
                    
                    res.id.append(tid)
                    res.cls.append(cls_id)
                    res.conf.append(score)
                    res.boxes.append(bbox)
        elif boxes_data is not None and len(boxes_data) > 0:
             # Detection Format
             # [class, score, x1, y1, x2, y2]
             det_arr = np.array(boxes_data)
             for row in det_arr:
                 if len(row) >= 6:
                     cls_id = int(row[0])
                     score = float(row[1])
                     bbox = row[2:6].tolist()
                     
                     res.id.append(None) # No track ID
                     res.cls.append(cls_id)
                     res.conf.append(score)
                     res.boxes.append(bbox)

        # 2. Attributes (res['attr'])
        # Usually: 'attr': {'age': [..], 'gender': [..]} PER object ?? Or List of dicts?
        # Based on PPLCNet, it usually returns a list of attributes per detected object (if tracking enabled, matched by ID)
        # However, Pipeline output might just be a 'attr' key with result.
        if 'attr' in raw_res:
            attrs = raw_res['attr']
            # If 'res' (MOT) exists, we might need to map by index if attr list corresponds to tracks.
            # Safety:
            if isinstance(attrs, list) and len(attrs) == len(res.id):
                 for i, attr_dict in enumerate(attrs):
                     tid = res.id[i]
                     if tid is not None:
                         res.attributes[tid] = attr_dict # e.g. {'gender': 'Male', 'age': '20'}
            # Note: If no tracking (boxes only), we can't easily map persistently, but can store by index if needed.

        # 3. Actions (STGCN, Smoking, Calling)
        # raw_res['action'] is for STGCN (Skeleton based)
        # raw_res['id_based_detaction'] (sic) or similar key for Smoking (Object Det)
        # raw_res['id_based_clsaction'] for Calling (Classification)
        
        # A. Skeleton Action (Fighting/Falling)
        if 'action' in raw_res:
             # actions list: [{'class': 0, 'score': 0.9, 'track_id': 1}, ...]
             actions = raw_res['action']
             if isinstance(actions, list):
                 for act in actions:
                     # DEBUG: Check format
                     # print(f"DEBUG: Action item: {act} Type: {type(act)}", flush=True)
                     
                     tid = None
                     cls = None
                     
                     if isinstance(act, dict):
                         tid = act.get('track_id')
                         cls = act.get('class')
                     elif isinstance(act, (list, tuple)) and len(act) >= 2:
                         # Assuming format (class, score, track_id) or similar? 
                         # Paddle output varies. Let's assume (class_id, score) or similar if not dict.
                         # Safest: try index if known? 
                         # Actually for now, just skip if not dict to avoid crash
                         continue
                     
                     if tid is not None:
                         # Map class ID to Name. 
                         # STGCN Fighting model: 0=Fighting (usually) or Falling? 
                         # Default generic model: 0=FallDown, 1=Fighting (need to verify model config)
                         # Users STGCN: usually trained on specific classes.
                         # Assuming standard: 
                         # If 'fighting' model: 0 = Fighting?
                         # Let's map generically based on string if available, else int.
                         # Better: map common IDs.
                         action_name = "unknown"
                         if cls == 0: action_name = "falling" # Often 0
                         elif cls == 1: action_name = "fighting" # Often 1
                         
                         # Check if 'label' key exists
                         if 'label' in act: action_name = act['label']
                         
                         res.actions[tid] = action_name

        # B. Smoking (Object Det based - often integrated into 'boxes' or separate key?)
        # In PPHuman pipeline code, it might inject into 'boxes' with specific class, OR 'smoking' key.
        # PP-Human v2 structure: often 'keypoint' or 'action' output. 
        # Actually, ID_BASED_DETECTION outputs might be merged?
        # Let's inspect 'boxes' classes. Smoking/Phone might be classes 80+?
        # OR separate keys.
        # Assuming separate processing (pipeline usually returns 'boxes' for main det, and specialized for others).
        # We will assume they might appear as attributes or separate actions. 
        # Ref: PPHuman Pipeline usually returns 'action' for all actions if unified.
        pass
        
        return res

class PPHumanResult:
    def __init__(self):
        self.boxes = [] # [x1, y1, x2, y2]
        self.conf = []
        self.cls = []
        self.id = [] # Track IDs
        
        # Extended Metadata
        self.attributes = {} # {idx: {"gender": "Male", ...}}
        self.actions = {}    # {idx: "fighting"}

    def __len__(self):
        return len(self.boxes)
