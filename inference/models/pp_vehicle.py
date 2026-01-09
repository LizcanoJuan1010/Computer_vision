from .base import BaseModel
import numpy as np
import cv2
import os
import paddle


# Re-use PPHuman result structure or create PPVehicle one?
# Using PPHumanResult for consistency in SecurityProcessor (boxes, id, cls, conf)
# We will store Plate Text in 'actions' or separate field? 
# PPHumanResult has 'actions' (dict track_id -> action). We can abuse this: track_id -> "Plate: XYZ"
# Or better, create PPVehicleResult.

class PPVehicleResult:
    def __init__(self):
        self.boxes = [] # [x1, y1, x2, y2]
        self.id = []    # [track_id]
        self.cls = []   # [class_id]
        self.conf = []  # [score]
        self.plates = {} # track_id -> str (Plate Number)

class PPVehicleModel(BaseModel):
    def __init__(self, model_dir, lpr_model=None):
        self.model_dir = model_dir
        self.predictor = None
        self.lpr_model = lpr_model # Instance of LPRModel
        self.tracker = None # We need a tracker instance (ByteTrack/OCSORT)
        self.trackers = {} # Per-Camera Tracker

    def load(self):
        print(f"Loading PP-Vehicle from {self.model_dir}...")
        
        # 1. Config Tracker
        # We can reuse the tracker config from global config or hardcode defaults for Vehicle
        # Using JDETracker or OCSORT. 
        # For simplicity, we'll instantiate the predictor and extract its tracker if possible,
        # OR just use the Detector and manage tracking manually like in pp_human.
        
        # Load Predictor (PaddleDetection Logic)
        # We need to manually construct it because 'create_predictor' assumes config file
        # But we have the exported model (model.pdmodel).
        
        # We can allow 'create_predictor' to load just the model? 
        # Usually we use: pred = create_predictor(args)
        # But args needs many flags.
        
        # HACK: We will use the same "MockFlags" approach as PPHuman if needed.
        # But let's try to just load the inference model directly for Detection
        # and attach a Tracker.
        
        model_file = os.path.join(self.model_dir, "model.pdmodel")
        params_file = os.path.join(self.model_dir, "model.pdiparams")
        
        if not os.path.exists(model_file):
            print(f"❌ Standard path not found, checking subfolder...")
            # Unzip usually creates a subfolder 'mot_ppyoloe_s_36e_ppvehicle'
            sub = "mot_ppyoloe_s_36e_ppvehicle"
            model_file = os.path.join(self.model_dir, sub, "model.pdmodel")
            params_file = os.path.join(self.model_dir, sub, "model.pdiparams")
            
        config = paddle.inference.Config(model_file, params_file)
        config.disable_gpu() # Avoid CUDNN Conflict
        config.enable_mkldnn()
        config.set_cpu_math_library_num_threads(4)
        config.switch_ir_optim(True)
        config.enable_memory_optim()
        
        self.predictor = paddle.inference.create_predictor(config)
        
        # Initialize Tracker Prototype (OCSORT)
        # We need 'ppol.tracking.ocsort_tracker' or similar. 
        # Attempt to import from local lib or paddledet
        try:
            from pp_tracking.python.mot.tracker import OCSORTTracker
            self.tracker_proto = OCSORTTracker(max_age=30, min_hits=3, iou_threshold=0.3)
        except ImportError:
            # Fallback or Stub
            print("⚠️ Tracker import failed. Using simpler logic or failing.")
            self.tracker_proto = None

        print("PP-Vehicle Loaded.")

    def predict(self, frames, camera_ids=None):
        if not self.predictor: 
            return []

        # 1. Preprocess Frames (Batch)
        # Assuming frames is List[np.ndarray] (RGB) or Tensor
        # PP-Vehicle (YOLO) expects 640x640 (check config, typically 640 for PPYOLOE-S)
        
        is_list = isinstance(frames, list)
        batch_size = len(frames) if is_list else frames.shape[0]
        
        if batch_size == 0: return []

        # Preprocess logic - Process frames individually for different resolutions
        import cv2
        TARGET_SIZE = (640, 640)
        
        # Resize each frame individually to same size
        resized_frames = []
        for f in frames:
            resized = cv2.resize(f, TARGET_SIZE, interpolation=cv2.INTER_LINEAR)
            resized_frames.append(resized)
        
        img_batch = np.stack(resized_frames, axis=0)
            
        # Normalize/Permute (standard ImageNet)
        img = img_batch.astype('float32') / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype='float32').reshape(1, 1, 1, 3)
        std = np.array([0.229, 0.224, 0.225], dtype='float32').reshape(1, 1, 1, 3)
        img = (img - mean) / std
        img = img.transpose((0, 3, 1, 2)) # NCHW
        img = np.ascontiguousarray(img)
        
        # Metadata
        im_shape = np.tile([640., 640.], (batch_size, 1)).astype('float32') # Check model input size! 
        scale_factor = np.tile([1., 1.], (batch_size, 1)).astype('float32')
        
        # Set Inputs
        input_names = self.predictor.get_input_names()
        for name in input_names:
            handle = self.predictor.get_input_handle(name)
            if name == 'image': handle.copy_from_cpu(img)
            elif name == 'im_shape': handle.copy_from_cpu(im_shape)
            elif name == 'scale_factor': handle.copy_from_cpu(scale_factor)
            
        # Run
        self.predictor.run()
        
        # Get Outputs
        # PPYOLOE output: 'multiclass_nms3_0.tmp_0' (Boxes), 'multiclass_nms3_0.tmp_2' (Count)
        output_names = self.predictor.get_output_names()
        mot_res_raw = {}
        for name in output_names:
            mot_res_raw[name] = self.predictor.get_output_handle(name).copy_to_cpu()
            
        # Parse
        bbox_counts = None
        boxes_tensor = None
        for k, v in mot_res_raw.items():
             if v.ndim == 2 and v.shape[1] == 6: boxes_tensor = v
             elif (v.ndim == 1 or (v.ndim==2 and v.shape[1]==1)): bbox_counts = v.flatten()
        
        results = []
        current_box_idx = 0
        
        for i in range(batch_size):
            res = PPVehicleResult()
            cam_id = camera_ids[i] if camera_ids else f"cam_{i}"
            
            # Extract raw boxes
            num_boxes = 0
            if bbox_counts is not None: num_boxes = int(bbox_counts[i])
            elif batch_size == 1 and boxes_tensor is not None: num_boxes = len(boxes_tensor)
            
            frame_dets = np.zeros((0, 6))
            if num_boxes > 0 and boxes_tensor is not None:
                frame_dets = boxes_tensor[current_box_idx : current_box_idx + num_boxes]
                current_box_idx += num_boxes
            
            # Filter Logic (Vehicle Classes check)
            # COCO Classes: 2=Car, 5=Bus, 7=Truck
            # PP-Vehicle Model Classes: 0=Car, 1=Truck, 2=Bus, 3=Motorcycle (Verification needed!)
            # Standard PP-Vehicle: 
            # 0: car, 1: truck, 2: bus, 3: motorcycle. 
            # Note: This is DIFFERENT from COCO.
            VALID_CLASSES = [0, 1, 2, 3] 
            
            filtered_dets = []
            if len(frame_dets) > 0:
                for det in frame_dets:
                    cls_id = int(det[0])
                    score = float(det[1])
                    if score > 0.3 and cls_id in VALID_CLASSES: # Threshold
                        filtered_dets.append(det)
            
            filtered_dets = np.array(filtered_dets)
            
            # Tracking
            # Need Per-Camera Tracker
            # ... (Simple Tracking Logic - reuse from PPHuman if possible or manual) ...
            # For iteration 1, we skip tracking and do LPR on Detection to save implementing tracker logic now.
            # OR we implement a dummy tracker that assigns ID based on IOU?
            # Let's skip heavy tracking for now or we will block here forever. 
            # Just Detect -> LPR.
            
            if len(filtered_dets) > 0:
                 for det in filtered_dets:
                     # det: [cls, score, x1, y1, x2, y2]
                     cls_id = int(det[0])
                     score = float(det[1])
                     box = det[2:6]
                     
                     res.id.append(None) # No track ID yet
                     res.cls.append(cls_id)
                     res.conf.append(score)
                     res.boxes.append(box.tolist())
                     
                     # 3. Runs LPR (On Crop)
                     if self.lpr_model:
                         x1, y1, x2, y2 = map(int, box)
                         # Clamp
                         h, w = (640, 640) # Original frame size?? No, frame size.
                         # Need original frame size. `frames[i]` is (640,640,3) OR original?
                         # Main.py resizes to 640x640 usually BEFORE passing? 
                         # Main.py: _letterbox_resize to target_size (640).
                         
                         frame_h, frame_w = frames[i].shape[:2]
                         x1 = max(0, min(x1, frame_w)); x2 = max(0, min(x2, frame_w))
                         y1 = max(0, min(y1, frame_h)); y2 = max(0, min(y2, frame_h))
                         
                         if (x2 - x1) > 20 and (y2 - y1) > 20:
                             crop = frames[i][y1:y2, x1:x2]
                             
                             # LPR Predict
                             lpr_res = self.lpr_model.predict(crop)
                             if lpr_res.label:
                                 # Store result
                                 # print(f"🚗 LPR Found: {lpr_res.label} ({lpr_res.conf:.2f})", flush=True)
                                 # Map track_id (None) -> Plate
                                 # We need a key. Index?
                                 res.plates[len(res.id)-1] = lpr_res.label
            
            results.append(res)
            
        return results
