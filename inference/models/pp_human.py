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
        if name == "run_mode": return "trt_fp16"
        print(f"DEBUG: MockFlags requested unknown attribute: {name}", flush=True)
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
                    self.illegal_parking_time = -1
                    
                    # Inference options
                    self.device = 'gpu' if paddle.is_compiled_with_cuda() else 'cpu'
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
            print(f"ℹ️ PPHuman Configured Device: {args.device.upper()}", flush=True)

            # Optimization: TensorRT
            if config.USE_TENSORRT and args.device.upper() == 'GPU':
                 print(f"🚀 Enabling TensorRT ({config.TENSORRT_PRECISION})...")
                 # Modes: paddle, trt_fp32, trt_fp16, trt_int8
                 # OPTIMIZATION: Force FP16
                 args.run_mode = 'trt_fp16'
                 
                 # Set TRT precision/shape info explicitly if needed
                 # For now, default pipeline logic handles it via run_mode

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
            print("✅ PP-Human: Pipeline initialized successfully.", flush=True)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"❌ Error initializing PP-Human Pipeline: {e}", flush=True)
            self.pipeline = None

    def predict(self, frame_or_batch, conf=0.5):
        # Handle Stub Mode
        if not self.pipeline:
             print("⚠️ PPHuman predict called but model is STUB.", flush=True)
             # Stub result
             results = []
             frames = frame_or_batch if isinstance(frame_or_batch, list) else [frame_or_batch]
             for _ in frames:
                 results.append(PPHumanResult()) # Empty
             return results

        # Manual Pipeline Orchestration
        results = []
        frames = frame_or_batch if isinstance(frame_or_batch, list) else [frame_or_batch]
        
        # print(f"ℹ️ PP-Human Predict Batch Size: {len(frames)}", flush=True)
        
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
                
                # Unified Logic: Handle both Tensor (GPU/DALI) and Numpy (CPU) via direct predictor
                # This bypasses the buggy 'preprocess' in PaddleDetection which fails on cv2.resize for dummy frames.
                
                # Check if input is a Tensor or Numpy (valid frame batch)
                is_tensor = isinstance(frame, paddle.Tensor)
                is_numpy = isinstance(frame, np.ndarray)

                if is_tensor or is_numpy:
                     # 1. Get Predictor
                     mot_predictor_obj = predictor.mot_predictor 
                     
                     # DEBUG: Inspect mot_predictor object structure
                     # print(f"DEBUG: mot_predictor type: {type(mot_predictor_obj)} dir: {dir(mot_predictor_obj)}", flush=True)
                     
                     try:
                         real_predictor = mot_predictor_obj.detector.predictor
                     except AttributeError:
                         # Fallback
                         # print(f"DEBUG: SDE_Detector has no .detector! dir: {dir(mot_predictor_obj)}", flush=True) 
                         if hasattr(mot_predictor_obj, 'det_predictor') and hasattr(mot_predictor_obj.det_predictor, 'predictor'):
                              real_predictor = mot_predictor_obj.det_predictor.predictor
                         elif hasattr(mot_predictor_obj, 'predictor'):
                              real_predictor = mot_predictor_obj.predictor
                         else:
                              raise AttributeError("Cannot find 'predictor' in mot_predictor object")

                     input_names = real_predictor.get_input_names()

                     # Normalize input to a list of frames for iteration
                     if is_tensor:
                         batch_size = frame.shape[0]
                         # Keep as tensor for zero-copy if possible, but for iteration we might need slices
                         # If it's a batch tensor, we iterate by index?
                         # Actually, to support tracking per-frame accurately, we should loop.
                         # But splitting a Tensor is cheap?
                         pass
                     else:
                         # Numpy
                         batch_size = frame.shape[0]

                     # Iterate batch to ensure correct tracking per frame
                     for i in range(batch_size):
                         # Extract single frame
                         if is_tensor:
                             sub_frame = frame[i] # Tensor slice
                             # Ensure dims [1, C, H, W] or [C, H, W]?
                             # DALI Tensor is usually NCHW or NHWC? DALI layout="HWC", so Tensor is NHWC?
                             # PP-YOLOE expects NCHW?
                             # Let's inspect shape if needed. Assuming DALI gave us what works?
                             pass
                         else:
                             sub_frame = frame[i] # Numpy slice (H, W, C)

                         # Prepare Input Handles
                     # Prepare Metadata (Batch Size 1 per frame in this loop)
                     bs = 1
                     im_shape = paddle.full([bs, 2], 640.0, dtype='float32') # Placeholder 640x640
                     scale_factor = paddle.full([bs, 2], 1.0, dtype='float32') 
                     
                     # Map Inputs
                     for name in input_names:
                         handle = real_predictor.get_input_handle(name)
                         if name == 'image':
                              if is_tensor:
                                  try:
                                      # Tensor Input (from DALI): uint8, HWC, RGB
                                      # Model expects: float32, NCHW, Normalized
                                      
                                      # DEBUG: Check Place
                                      # print(f"DEBUG: Frame Place: {frame.place}", flush=True)

                                      # 1. Cast to Float32 & Scale
                                      input_tensor = paddle.cast(frame, 'float32') / 255.0
                                      
                                      # 2. Normalize (Mean/Std)
                                      # BUGFIX: frame.place can return gpu:-1. Use explicit CUDAPlace(0)
                                      gpu_place = paddle.CUDAPlace(0)
                                      mean = paddle.to_tensor([0.485, 0.456, 0.406], place=gpu_place).reshape([1, 1, 3])
                                      std = paddle.to_tensor([0.229, 0.224, 0.225], place=gpu_place).reshape([1, 1, 3])
                                      input_tensor = (input_tensor - mean) / std
                                      
                                      # 3. Permute HWC -> CHW (2, 0, 1)
                                      input_tensor = paddle.transpose(input_tensor, perm=[2, 0, 1])
                                      
                                      # 4. Add Batch Dim -> NCHW (1, 3, 640, 640)
                                      input_tensor = input_tensor.unsqueeze(0)
                                      
                                      # Pass to handle
                                      handle.share_external_data(input_tensor)
                                  except Exception as e:
                                      print(f"⚠️ GPU Preprocess Failed: {e}. Fallback to CPU.", flush=True)
                                      # Fallback: Convert to Numpy (Copy to CPU) and use CPU logic
                                      
                                      # 1. BGR -> RGB for Inference (Wait, frame is RGB from DALI if tensor)
                                      # If it was tensor, it came from main.py as RGB.
                                      # If main.py gpu_batch is RGB.
                                      
                                      img_cpu = frame.numpy() # RGB
                                      
                                      # 2. Resize to 640x640 (Model Input Size)
                                      img = cv2.resize(img_cpu, (640, 640))
                                      
                                      # 3. Normalize and Transpose
                                      img = img.astype('float32') / 255.0
                                      mean = np.array([0.485, 0.456, 0.406], dtype='float32').reshape(1, 1, 3)
                                      std = np.array([0.229, 0.224, 0.225], dtype='float32').reshape(1, 1, 3)
                                      img = (img - mean) / std
                                      img = img.transpose((2, 0, 1)) # HWC -> CHW
                                      img = img[np.newaxis, :] # Add batch dim
                                      img = np.ascontiguousarray(img)
                                      
                                      handle.copy_from_cpu(img)
                              else:
                                  # Numpy Input (Passed from Main as BGR)
                                  # Model expects: float32, NCHW, RGB Normalized
                                  
                                  # 1. BGR -> RGB for Inference
                                  img = frame[:, :, ::-1] # BGR -> RGB
                                  
                                  # DEBUG: Check Input
                                  print(f"🖼️ PRE-PROCESS: Input Shape {img.shape}, Mean {img.mean():.2f}, Dtype={img.dtype}, Min={img.min()}, Max={img.max()}", flush=True)
                                  
                                  # 2. Resize to 640x640 (Model Input Size)
                                  # DALI gives 640x360. Model needs 640x640.
                                  img = cv2.resize(img, (640, 640))
                                  
                                  # 3. Normalize and Transpose
                                  img = img.astype('float32') / 255.0
                                  mean = np.array([0.485, 0.456, 0.406], dtype='float32').reshape(1, 1, 3)
                                  std = np.array([0.229, 0.224, 0.225], dtype='float32').reshape(1, 1, 3)
                                  img = (img - mean) / std
                                  img = img.transpose((2, 0, 1)) # HWC -> CHW
                                  img = img[np.newaxis, :] # Add batch dim -> (1, 3, 640, 640)
                                  
                                  # Ensure contiguous memory
                                  img = np.ascontiguousarray(img)
                                  
                                  handle.copy_from_cpu(img)

                         elif name == 'im_shape':
                             if is_tensor: handle.share_external_data(im_shape)
                             else: handle.copy_from_cpu(im_shape.numpy())
                         elif name == 'scale_factor':
                             if is_tensor: handle.share_external_data(scale_factor)
                             else: handle.copy_from_cpu(scale_factor.numpy())
                             
                     # Run Inference
                     real_predictor.run()
                     
                     # Get Outputs
                     output_names = real_predictor.get_output_names()
                     mot_res_raw = {}
                     for name in output_names:
                         out_tensor = real_predictor.get_output_handle(name)
                         mot_res_raw[name] = out_tensor.copy_to_cpu()
                         
                     # Run Tracker
                     dets = np.zeros((0, 6))
                     for k, v in mot_res_raw.items():
                         if v.ndim == 2 and v.shape[1] == 6:
                             dets = v
                             break
                     
                     # Force Filter Low Confidence (Fix for "100 boxes" noise)
                     # User complained about no identification, but logs show 0.4-0.5. 
                     # We set threshold to 0.05 to catch real detections while filtering garbage
                     DET_THRESHOLD = 0.05
                     if len(dets) > 0:
                         # DEBUG: Print Raw Scores before filter
                         print(f"🔎 DEBUG: Raw Scores (top 5): {dets[:5, 1]}", flush=True)
                         keep_mask = dets[:, 1] > DET_THRESHOLD
                         dets = dets[keep_mask]

                     # Minimal Debug
                     if len(dets) > 0:
                         max_score = np.max(dets[:, 1])
                         curr_count = len(dets)
                         if max_score > DET_THRESHOLD:
                            print(f"🕵️ DETECTED: {curr_count} boxes (Filtered > {DET_THRESHOLD}). Max: {max_score:.2f}", flush=True)
                            # Print first 3 boxes to check for garbage coordinates
                            for i in range(min(3, len(dets))):
                                box = dets[i]
                                print(f"   Box[{i}]: Score={box[1]:.4f} Class={box[0]} Coords={box[2:]}", flush=True)
                     else:
                         # Print if we filtered everything
                         pass
                         # print("DEBUG: No boxes passed threshold filter", flush=True)
                     
                     tracker = mot_predictor_obj.tracker
                     # Handle tracker update
                     track_res = tracker.update(dets, None) 
                     
                     # Populate 'res'
                     for trk in track_res:
                         tid = int(trk[4])
                         score = float(trk[5])
                         cls_id = int(trk[6])
                         bbox = trk[0:4].tolist()
                         # FILTER: Threshold check
                         # We lower this to match the input filter (0.1)
                         if score >= 0.1: 
                             res.id.append(tid)
                             res.cls.append(cls_id)
                             res.conf.append(score)
                             res.boxes.append(bbox)
                             # DEBUG: Print Track Accept
                             # print(f"✅ Track Accepted: ID={tid} Score={score:.2f}", flush=True)
                         
                     # Construct 'mot_res' for downstream
                     mot_res = {'boxes': []}
                     for i in range(len(res.id)):
                         row = [res.id[i], res.cls[i], res.conf[i]] + res.boxes[i]
                         mot_res['boxes'].append(row)
                         
                     # Prepare 'frame' for downstream (Numpy)
                     if is_tensor:
                         frame_cpu = frame.numpy()
                         if frame_cpu.shape[0] == 3: # CHW
                             frame_cpu = np.transpose(frame_cpu, (1, 2, 0))
                         # RGB to BGR for OpenCV (Visualization)
                         frame = frame_cpu[:, :, ::-1]
                     else:
                         # Numpy input is BGR (from Main)
                         # Visualization expects BGR. 
                         # No conversion needed.
                         pass

                else:
                    # Fallback (Should be unreachable if input is Tensor or Numpy)
                    pass

                has_detections = len(res.id) > 0
                
                # 2. Attributes (Optional)
                if predictor.with_human_attr and has_detections:
                    crop_input, new_bboxes, ori_bboxes = crop_image_with_mot(frame, mot_res)
                    attr_res = predictor.attr_predictor.predict_image(crop_input, visual=False)
                    if 'output' in attr_res:
                        attrs_list = attr_res['output']
                        for i, attr in enumerate(attrs_list):
                            if i < len(res.id):
                                tid = res.id[i]
                                res.attributes[tid] = attr

                # 3. Action (Skeleton)
                if predictor.with_skeleton_action and has_detections:
                    if not 'crop_input' in locals():
                        crop_input, new_bboxes, ori_bboxes = crop_image_with_mot(frame, mot_res)
                    kpt_pred = predictor.kpt_predictor.predict_image(crop_input, visual=False)
                    skeleton_res = predictor.skeleton_action_predictor.predict_skeleton_with_mot(mot_res, kpt_pred)
                    
                    if isinstance(skeleton_res, list):
                        for act in skeleton_res:
                            tid = act.get('track_id')
                            cls = act.get('class', -1)
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
                             label = act.get('label')
                             if tid is not None and label:
                                 res.actions[tid] = label

                # 5. Action (Classification based - Calling)
                from datetime import datetime
                now = datetime.now()
                night_mode = (now.hour >= 22 or now.hour < 5)
                call_threshold = 0.4 if night_mode else 0.8
                
                if getattr(predictor, 'with_idbased_clsaction', False) and has_detections:
                     if hasattr(predictor, 'cls_action_predictor') and hasattr(predictor.cls_action_predictor, 'threshold'):
                             predictor.cls_action_predictor.threshold = call_threshold
                     if not 'crop_input' in locals():
                        crop_input, new_bboxes, ori_bboxes = crop_image_with_mot(frame, mot_res)
                     cls_action_res = predictor.cls_action_predictor.predict(crop_input, mot_res)
                     if isinstance(cls_action_res, list):
                         for act in cls_action_res:
                             tid = act.get('track_id')
                             label = act.get('label')
                             if tid is not None and label:
                                 res.actions[tid] = label

            except Exception as e:
                print(f"PP-Human Prediction Error: {e}")
                import traceback
            
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
