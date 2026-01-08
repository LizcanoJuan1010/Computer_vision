import os
import cv2
import yaml
import numpy as np
import paddle
from ..config import config

try:
    # Try importing from the cloned PaddleDetection repo (in Docker PYTHONPATH)
    from deploy.pipeline.pipeline import Pipeline, PipePredictor
    from deploy.python.infer import Detector
    from ppdet.core.workspace import load_config
    # Utils for manual pipeline
    # Utils for manual pipeline
    from deploy.pipeline.pipe_utils import parse_mot_res, crop_image_with_mot
    import sys
    # SYSTEM FIX: Patch deploy.python.infer to avoid NameError: name 'FLAGS' is not defined
    # The PaddleDetection library uses a global FLAGS variable. We inject it directly into the module dictionary.
    
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
            if name == "run_mode": return "trt_fp16"
            if name == "run_mode": return "trt_fp16"
            print(f"DEBUG: MockFlags requested unknown attribute: {name}", flush=True)
            return "" # Return empty string to act as False but satisfy path requirements
            
    mock_flags = MockFlags()
    
    # Force patch sys.modules to ensure our mock is used even if Dockerfile predefined it
    for mod_name in ['deploy.python.infer', 'infer', 'deploy.pipeline.pipeline']:
        if mod_name in sys.modules:
            print(f"DEBUG: Force Injecting Mock FLAGS into {mod_name}", flush=True)
            try:
                setattr(sys.modules[mod_name], 'FLAGS', mock_flags)
            except Exception as e:
                print(f"DEBUG: Failed to inject FLAGS into {mod_name}: {e}")

    # Also force set in the local imported module
    try:
        import deploy.python.infer as infer_mod
        infer_mod.FLAGS = mock_flags
        
        # SYSTEM FIX: Monkeypatch create_predictor to disable IR Optimization
        # This prevents CUDNN_STATUS_NOT_SUPPORTED errors in fused convolutions on some GPUs
        if hasattr(infer_mod, 'create_predictor'):
            _orig_create_predictor = infer_mod.create_predictor
            def _patched_create_predictor(opt_config):
                print("DEBUG: Patched create_predictor called. Disabling IR Optim.", flush=True)
                if hasattr(opt_config, 'switch_ir_optim'):
                    opt_config.switch_ir_optim(False)
                return _orig_create_predictor(opt_config)
            infer_mod.create_predictor = _patched_create_predictor
            print("DEBUG: Successfully patched infer_mod.create_predictor", flush=True)

    except ImportError:
        pass
        print("DEBUG: Force Injecting Mock FLAGS into imported deploy.python.infer", flush=True)
    except ImportError:
        pass
    
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
                    self.device = 'CPU' # FORCE CPU to bypass CUDNN crash
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

            # Optimization: TensorRT
            if config.USE_TENSORRT and args.device.upper() == 'GPU':
                 print(f"🚀 Enabling TensorRT ({config.TENSORRT_PRECISION})...")
                 # Modes: paddle, trt_fp32, trt_fp16, trt_int8
                 # OPTIMIZATION: Force FP16
                 args.run_mode = 'trt_fp16'

            print("DEBUG: Pipeline init started", flush=True)
            try:
                self.pipeline = Pipeline(args, self.cfg)
                self.pipeline.cfg = self.cfg # Explicitly set if Pipeline doesn't
            except Exception as e:
                # Basic Fallback logic
                print(f"⚠️ Pipeline Init Error: {e}")
                if config.USE_TENSORRT and args.run_mode.startswith('trt'):
                     print("⚠️ TensorRT failed. Falling back to standard Paddle Inference...")
                     args.run_mode = 'paddle'
                     self.pipeline = Pipeline(args, self.cfg)
                     self.pipeline.cfg = self.cfg
                else:
                     raise e
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
                try:
                   from nvidia.dali import pipeline_def, fn
                   import nvidia.dali.types as types
                   HAS_DALI = True
                except ImportError:
                   HAS_DALI = False

                # 1. MOT (Detection + Tracking)
                # predict_image(image_list, visual=False, reuse_det_result=False, frame_count=frame_id)
                # Input must be list of frames (numpy)
                
                # OPTIMIZATION: DALI Tensor Support (DLPack / Paddle Tensor)
                # If frame is already a Paddle Tensor (on GPU), bypass preprocessing
                
                # OPTIMIZATION: DALI Tensor Support (DLPack / Paddle Tensor)
                # If frame is already a Paddle Tensor (on GPU), bypass preprocessing
                
                # Check if input is a Tensor
                if isinstance(frame, paddle.Tensor):
                     print(f"DEBUG: DALI Tensor Input Shape: {frame.shape}", flush=True)
                     
                     # 1. Get Predictor
                     mot_predictor_obj = predictor.mot_predictor 
                     real_predictor = mot_predictor_obj.detector.predictor
                     input_names = real_predictor.get_input_names()

                     # Prepare Meta Info
                     # Since we iterate, bs=1
                     bs = 1
                     im_shape = paddle.full([bs, 2], 640.0, dtype='float32') # Placeholder 640x640
                     scale_factor = paddle.full([bs, 2], 1.0, dtype='float32') 
                     
                     # 2. Map inputs (Zero-Copy)
                     for name in input_names:
                         handle = real_predictor.get_input_handle(name)
                         if name == 'image':
                             # Ensure correct rank if needed. [C, H, W] -> [1, C, H, W] ??
                             # If frame is 3D, we might need unsqueeze. 
                             # However, let's assume DALI gave us what matches the model batch?
                             # Typically PP-YOLOE expects [B, 3, H, W].
                             if len(frame.shape) == 3:
                                  frame_input = frame.unsqueeze(0)
                                  handle.share_external_data(frame_input)
                             else:
                                  handle.share_external_data(frame) 
                         elif name == 'im_shape':
                             handle.share_external_data(im_shape)
                         elif name == 'scale_factor':
                             handle.share_external_data(scale_factor)
                             
                     # 3. Run Inference (Detection)
                     real_predictor.run()
                     
                     # 4. Get Outputs
                     output_names = real_predictor.get_output_names()
                     mot_res_raw = {}
                     for name in output_names:
                         out_tensor = real_predictor.get_output_handle(name)
                         mot_res_raw[name] = out_tensor.copy_to_cpu()
                         
                     # 5. Run Tracker (CPU)
                     # We need to parse detection results and feed to tracker.
                     # Detection output is usually [N, 6] (cls, score, x, y, x, y)
                     # Find the boxes tensor
                     dets = np.zeros((0, 6))
                     for k, v in mot_res_raw.items():
                         if v.ndim == 2 and v.shape[1] == 6:
                             dets = v
                             break
                             
                     tracker = mot_predictor_obj.tracker
                     # Tracker expects [cls, score, x, y, x, y]
                     track_res = tracker.update(dets, None) # [x1, y1, x2, y2, id, score, cls, ...]
                     
                     # 6. Populate 'res'
                     for trk in track_res:
                         tid = int(trk[4])
                         score = float(trk[5])
                         cls_id = int(trk[6])
                         bbox = trk[0:4].tolist()
                         
                         res.id.append(tid)
                         res.cls.append(cls_id)
                         res.conf.append(score)
                         res.boxes.append(bbox)
                     
                     # 7. Prepare for Attributes/Actions (CPU)
                     # Subsequent blocks use 'frame' (numpy) and 'mot_res' (dict)
                     # We need to construct 'mot_res' dict manually from our tracker results
                     # because 'crop_image_with_mot' uses it.
                     # Format: {'boxes': [[id, cls, score, x1, y1, x2, y2], ...]}
                     
                     mot_res = {'boxes': []}
                     for i in range(len(res.id)):
                         row = [res.id[i], res.cls[i], res.conf[i]] + res.boxes[i]
                         mot_res['boxes'].append(row)
                         
                     # Convert GPU Tensor frame to CPU Numpy for 'crop_image' and subsequent predictors
                     # Transpose if needed? DALI is CHW mostly. OpenCv is HWC BGR.
                     # DALI Pipeline output_type=types.RGB.
                     # So frame is [C, H, W] RGB.
                     # We need [H, W, C] BGR for OpenCV functions downstream.
                     
                     frame_cpu = frame.numpy() # [C, H, W]
                     if frame_cpu.shape[0] == 3: # CHW
                         frame_cpu = np.transpose(frame_cpu, (1, 2, 0)) # [H, W, C]
                         
                     # RGB to BGR?
                     # DALI gave RGB. PP-Human predictors usually expect BGR/RGB? 
                     # `predict_image` usually loads via cv2.imread (BGR).
                     # So expected input is BGR.
                     frame_cpu = frame_cpu[:, :, ::-1] # RGB to BGR
                     
                     # Overwrite local frame variable
                     frame = frame_cpu
                     
                     # Fall through to Attribute/Action blocks...
                     
                else:
                    # Standard CPU path (OpenCV/Numpy)
                    # ... [Original Logic]
                    print(f"DEBUG: Frame shape: {frame.shape}", flush=True)
                    
                    # Handle Batch (4D) Input
                    if frame.ndim == 4:
                        mot_input = [frame[i] for i in range(frame.shape[0])]
                    else:
                        mot_input = [frame]

                    mot_res_raw = predictor.mot_predictor.predict_image(
                        mot_input, visual=False, reuse_det_result=False, frame_count=self.frame_id
                    )
                    mot_res = parse_mot_res(mot_res_raw)
                    if 'boxes' in mot_res:
                         for row in mot_res['boxes']:
                             if len(row) >= 7:
                                 tid = int(row[0])
                                 cls_id = int(row[1])
                                 score = float(row[2])
                                 bbox = row[3:7].tolist()
                                 res.id.append(tid)
                                 res.cls.append(cls_id)
                                 res.conf.append(score)
                                 res.boxes.append(bbox)
                    
                    has_detections = len(res.boxes) > 0
        

                
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

        # B. Smoking and Calling (ID Based)
        # PP-Human result structure for these can vary (separate keys).
        
        # 1. Smoking (Detection based)
        # raw_res key: 'id_based_detaction' (sic) - list of dicts {class_id, score, track_id, label}
        if 'id_based_detaction' in raw_res:
            smoking_acts = raw_res['id_based_detaction']
            if isinstance(smoking_acts, list):
                for act in smoking_acts:
                    tid = act.get('track_id')
                    label = act.get('label') # e.g. "smoking"
                    if tid is not None and label:
                         res.actions[tid] = label

        # 2. Calling (Classification based)
        # raw_res key: 'id_based_clsaction' - list of dicts {class_id, score, track_id, label}
        if 'id_based_clsaction' in raw_res:
             calling_acts = raw_res['id_based_clsaction']
             if isinstance(calling_acts, list):
                 for act in calling_acts:
                     tid = act.get('track_id')
                     label = act.get('label') # e.g. "calling"
                     if tid is not None and label:
                          res.actions[tid] = label
        
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
        self.reid_features = {} # {track_id: np.array} (ReID Embeddings)
        self.global_events = [] # ["fight_detection"] (Frame-level events)
