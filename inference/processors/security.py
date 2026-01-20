import cv2
import time
from ..config import config
from .core import BaseProcessor

from .spatial import SpatialAnalytics

class SecurityProcessor(BaseProcessor):
    def __init__(self, db, yolo_model, face_model, vehicle_model, lpr_model=None, face_cache=None, publish_callback=None, loop=None):
        self.db = db
        self.yolo_model = yolo_model
        self.face_model = face_model
        self.vehicle_model = vehicle_model # Renamed/Added
        self.lpr_model = lpr_model # Added (ONNX LPR)
        self.face_cache = face_cache  # FaceCacheLFU instance
        self.publish_callback = publish_callback
        self.loop = loop # Main Event Loop for thread-safe async calls
        # Initialize Spatial Analytics (Tracking, Zones)
        self.spatial = SpatialAnalytics()

        self.frame_counter = 0
        self.SKIP_FACTOR = 1  # Process every frame for stability/debugging
        self.track_state = {} 
        self.lpr_cooldowns = {} # Added: {cam_id: {plate: last_t}}
        self.face_alert_cooldowns = {} # Added: {cam_id: {key: last_t}}
        
        # ThreadPool for LPR (IO/CPU heavy per crop)
        import concurrent.futures
        self.lpr_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


    def save_event_async(self, *args, **kwargs):
        """Offload DB writes to default executor to avoid blocking inference loop."""
        if self.loop:
            # We use run_in_executor to fire and forget (mostly)
            # Use partial to pass kwargs
            from functools import partial
            func = partial(self.db.save_event, *args, **kwargs)
            self.loop.run_in_executor(None, func)
        else:
            # Fallback
            self.db.save_event(*args, **kwargs)

    def _handle_face_event(self, camera_id, name, category, similarity, is_from_global, abs_box):
         # Helper to reduce complexity in main loop
         curr_time = time.time()
         if not hasattr(self, "face_alert_cooldowns"): self.face_alert_cooldowns = {}
         if camera_id not in self.face_alert_cooldowns: self.face_alert_cooldowns[camera_id] = {}
         
         debounce_key = f"{name}_{category}"
         last_face_alert = self.face_alert_cooldowns[camera_id].get(debounce_key, 0)
         
         if (curr_time - last_face_alert) > 5.0: 
            severity = "HIGH" if category == 'BLACKLIST' else "INFO"
            self.save_event_async(
                camera_id, 
                "face_recognition", 
                name,
                confidence=float(similarity),
                bbox=abs_box,
                severity=severity
            )
            self.face_alert_cooldowns[camera_id][debounce_key] = curr_time

    def _handle_unknown_face(self, camera_id, org_id, cfg_data, embedding):
        is_restricted = cfg_data.get("is_restricted_zone", False) if cfg_data else False
        auto_save = cfg_data.get("auto_save_unknown", False) if cfg_data else False

        if is_restricted and auto_save and org_id:
             curr_time = time.time()
             if not hasattr(self, "unknown_save_cooldown"): self.unknown_save_cooldown = {}
             last_save = self.unknown_save_cooldown.get(camera_id, 0)
             
             if (curr_time - last_save) > 5.0:
                  try:
                      timestamp = int(curr_time)
                      auto_name = f"Unknown_{timestamp}"
                      import json
                      self.db.cur.execute("""
                          INSERT INTO faces (name, embedding, organization_id, category, meta_info) 
                          VALUES (%s, %s, %s, 'UNKNOWN', '{"auto_saved": true}')
                      """, (auto_name, embedding.tolist(), org_id))
                      self.db.conn.commit()
                      
                      self.unknown_save_cooldown[camera_id] = curr_time
                      print(f"🚨 Auto-saved UNKNOWN face: {auto_name}")
                      
                      if self.publish_callback:
                          self.publish_callback("events.alarm", {
                              "camera_id": camera_id,
                              "event_type": "security_alert",
                              "severity": "HIGH",
                              "message": f"Security Breach: Unrecognized person in Restricted Zone"
                          })
                  except Exception as e:
                      print(f"Error auto-saving unknown face: {e}")
                      self.db.conn.rollback()

    def process_batch(self, frames, camera_ids, configs, gpu_frames=None):
        print(f"🔄 DEBUG: process_batch START ({len(frames)} frames). Shape: {frames[0].shape}", flush=True)
        start_time = time.time()
        
        # --- 1. PP-Human Inference (Batch) ---
        # GPU Optimization: Use GPU frames if available
        # Pass camera configs so Pose only runs for cameras with action features
        if gpu_frames is not None:
             pp_results_batch = self.yolo_model.predict(gpu_frames, camera_ids=camera_ids, camera_configs=configs)
        else:
             pp_results_batch = self.yolo_model.predict(frames, camera_ids=camera_ids, camera_configs=configs)
        
        print(f"🔄 DEBUG: YOLO finished", flush=True)
        
        # DEBUG: Print detection stats
        for i, res in enumerate(pp_results_batch):
             if len(res.boxes) > 0:
                 print(f"[{camera_ids[i]}] Detectados: {len(res.boxes)} personas/objetos", flush=True)
        
        # Increment counter
        self.frame_counter += 1
        run_heavy_models = (self.frame_counter % self.SKIP_FACTOR == 0)
        # --- 2. PP-Vehicle Inference (REMOVED - Unified with YOLO) ---
        # We no longer run a separate vehicle model inference.
        # Everything (Person/Car/Bus/Truck) is now handled by yolo_model in one batch.
        pp_vehicle_results = [] # Placeholder for compatibility if needed elsewhere
        
        # --- 3. Prepare Face Recognition Batch (with Track Caching) ---
        face_crops = []
        face_metadata = [] # (batch_index, track_id, bbox, config_data)
        
        # Initialize results map early to fill with cached items
        face_results_map = {i: [] for i in range(len(frames))}
        
        current_time = time.time()
        
        # Cleanup cache if too big
        if len(self.track_state) > 5000:
             self.track_state.clear()

        # RECHECK_INTERVAL: How often to re-run Face Recognition on a tracked person (seconds)
        RECHECK_INTERVAL = 3.0 

        for i, (frame, pp_results) in enumerate(zip(frames, pp_results_batch)):
             config_data = configs[i]
             features = config_data.get("features", []) if config_data else ["face", "line_crossing", "intrusion"]
             camera_id = camera_ids[i]
             print(f"⚙️ DEBUG-CONFIG [{camera_id}] Enabled Features: {features}", flush=True)
             
             print(f"👤 DEBUG-FACE: Camera {camera_id}: 'face' in features = {'face' in features}, has_boxes = {hasattr(pp_results, 'boxes')}, num_boxes = {len(pp_results.boxes) if hasattr(pp_results, 'boxes') else 0}", flush=True)
             
             if "face" in features and hasattr(pp_results, 'boxes'):
                 for j, bbox_raw in enumerate(pp_results.boxes):
                     
                     # 1. Get Track ID
                     tid = None
                     if hasattr(pp_results, 'id') and len(pp_results.id) > j:
                         # pp_results.id[j] might be None if detection only
                         raw_tid = pp_results.id[j]
                         if raw_tid is not None:
                             tid = f"{camera_id}_{int(raw_tid)}"
                     
                     cls_id = int(pp_results.cls[j]) if len(pp_results.cls) > j else 0
                     
                     if cls_id == 0: # Person
                         x1, y1, x2, y2 = bbox_raw
                         h, w = frame.shape[:2]
                         x1, y1 = max(0, int(x1)), max(0, int(y1))
                         x2, y2 = min(w, int(x2)), min(h, int(y2))
                         
                         abs_box = (x1, y1, x2, y2)
                         
                         # Check Cache
                         cached_ident = None
                         should_process = True
                         
                         if tid and tid in self.track_state:
                             # We have a history
                             state = self.track_state[tid]
                             age = current_time - state['last_check']
                             
                             if age < RECHECK_INTERVAL:
                                 # Use Cache!
                                 should_process = False
                                 cached_ident = state
                             else:
                                 # Time to re-verify
                                 should_process = True
                                 # But we can tentatively display old name while processing?
                                 # For simplicity, we just process. 
                                 pass
                         
                         # If no tracking data, we MUST process every frame (expensive!)
                         if not tid:
                             should_process = True

                         # Optimization: Skip processing completely if "SKIP" factor and NOT timed out?
                         # The global self.frame_counter skip is crude. 
                         # Better: if we have cache, use it. If not, only process keyframes?
                         # For now, let's rely on track cache + global skip for untracked.
                         if should_process and not run_heavy_models and not tid:
                             continue # Skip untracked on non-heavy frames
                             
                         # Force process if track needs update, OR if untracked and heavy frame
                         # Actually logic above: if should_process is True, we run it.
                         # But wait, original code skipped ALL if not run_heavy_models.
                         # We want to run IF (Heavy Frame) OR (Track needs Update).
                         # If (Not Heavy) AND (Track valid) -> Use Cache.
                         # If (Not Heavy) AND (Track Expired) -> Update? Yes, keep fresh.
                         # If (Not Heavy) AND (No Track) -> Skip (wait for heavy frame).
                         
                         if not run_heavy_models and should_process:
                             # It's a light frame, but we "should" process.
                             # If we have a track but it expired, maybe we delay update to next heavy frame?
                             # To keep FPS high, let's ONLY process on heavy frames, 
                             # UNLESS we have absolutely no info?
                             # Let's stick to: Update only on heavy frames, OR use cache.
                             if tid and tid in self.track_state:
                                 # Use stale cache for a bit longer until heavy frame hits
                                 cached_ident = self.track_state[tid]
                                 should_process = False
                             else:
                                 # No track, and light frame -> Skip
                                 should_process = False
                         
                         if should_process:
                             if x2 > x1 and y2 > y1:
                                 print(f"✂️ DEBUG-FACE-CROP: Creating face crop from person bbox ({x1},{y1},{x2},{y2})", flush=True)
                                 face_crop = frame[y1:y2, x1:x2]
                                 face_crops.append(face_crop)
                                 face_metadata.append((i, tid, abs_box, config_data))
                             else:
                                 print(f"⚠️ DEBUG-FACE-CROP: Invalid bbox ({x1},{y1},{x2},{y2}), skipping", flush=True)
                         elif cached_ident:
                             # Add cached result
                             name = cached_ident['name']
                             color = cached_ident['color']
                             face_results_map[i].append((abs_box, name, color))

        # --- 3. Batch Face Recognition ---
        print(f"👤 DEBUG-FACE-BATCH: Total face_crops to process: {len(face_crops)}", flush=True)
        if face_crops:
            print(f"⚡ DEBUG: Analyzing {len(face_crops)} detected faces...", flush=True)
            # Predict all faces at once
            print(f"🔄 DEBUG: Face Model Predict Start", flush=True)
            all_faces_analysis = self.face_model.predict(face_crops)
            print(f"🔄 DEBUG: Face Model Predict End", flush=True)
            print(f"✅ DEBUG: YuNet returned {len(all_faces_analysis)} results", flush=True)
            
            # Prepare Parallel Search Tasks
            search_tasks = []
            search_metadata = []

            for k, faces in enumerate(all_faces_analysis):
                # Metadata
                batch_idx, tid, crop_bbox, cfg_data = face_metadata[k]
                
                if not faces: continue
                
                # Sort by size (largest face)
                faces = sorted(faces, key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]), reverse=True)
                primary_face = faces[0]
                
                # Config
                threshold = config.SIMILARITY_THRESHOLD
                face_cfg = cfg_data.get("face_config") if cfg_data else None
                if face_cfg and "threshold" in face_cfg:
                    threshold = float(face_cfg["threshold"])
                org_id = cfg_data.get("org_id") if cfg_data else None

                # Create Search Task
                task_meta = {
                    "k": k,
                    "primary_face": primary_face,
                    "threshold": threshold,
                    "org_id": org_id,
                    "camera_id": camera_ids[face_metadata[k][0]],
                    "crop_bbox": crop_bbox,
                    "cfg_data": cfg_data
                }
                
                if self.face_cache and org_id and self.loop:
                     import asyncio
                     future = asyncio.run_coroutine_threadsafe(self.face_cache.search(
                        query_embedding=primary_face.embedding,
                        org_id=org_id,
                        threshold=threshold,
                        include_global_blacklist=True
                     ), self.loop)
                     search_tasks.append(future)
                     search_metadata.append(task_meta)
                else:
                    # Fallback Sync DB (Cannot parallelize easily without threadpool)
                    # Treat as immediate result
                    search_tasks.append(None) 
                    search_metadata.append(task_meta)

            # Wait for all async tasks (Parallel Execution)
            results = []
            for future in search_tasks:
                if future:
                    try:
                        results.append(future.result(timeout=2.0))
                    except Exception as e:
                        print(f"Face Cache Future Error: {e}")
                        results.append(None)
                else:
                    results.append(None)

            # Process Results
            print(f"🔄 DEBUG: Async Search/DB finished", flush=True)
            for i, result in enumerate(results):
                meta = search_metadata[i]
                primary_face = meta["primary_face"]
                k = meta["k"]
                
                match = result
                
                # Fallback if no cache result
                if not match and not search_tasks[i]: 
                     # Only run DB fallback if we didn't use cache or cache failed locally
                     # (In this logic, if tasks[i] was None, it means we must use Sync DB)
                     db_match = self.db.find_nearest_face(primary_face.embedding)
                     if db_match:
                        db_name, distance = db_match
                        req_dist = 1.0 - meta["threshold"]
                        if distance < req_dist:
                            match = (None, db_name, 'KNOWN', 1.0 - distance, False)

                # Determine Result
                batch_idx = face_metadata[k][0] # Map back to frame index
                
                if match:
                    face_id, name, category, similarity, is_from_global = match
                    cam_id_for_event = camera_ids[batch_idx]
                    self._handle_face_event(cam_id_for_event, name, category, similarity, is_from_global, crop_bbox)

                else:
                    name = "Unknown"
                    color = (0, 0, 255)
                    # Check Auto-save - use camera_ids[batch_idx] instead of undefined camera_id
                    cam_id_for_event = camera_ids[batch_idx]
                    self._handle_unknown_face(cam_id_for_event, org_id, cfg_data, primary_face.embedding)

                # Store absolute bbox relative to original frame? 
                # Note: The crop was from the frame, so face bbox is relative to crop.
                # Need to adjust.
                fx1, fy1, fx2, fy2 = primary_face.bbox.astype(int)
                abs_face_box = (cx1 + fx1, cy1 + fy1, cx1 + fx2, cy1 + fy2)
                
                # Update Track State
                if tid:
                    self.track_state[tid] = {
                        'name': name,
                        'color': color,
                        'last_check': current_time
                    }
                
                face_results_map[batch_idx].append((abs_face_box, name, color))



        # --- 4. Spatial Analysis & Visualization (Per Frame) ---
        processed_frames = []
        batch_metadata = [] # List of dicts per frame

        
        TARGET_SIZE = (640, 640)  # Visualization size
        
        for i, (frame, pp_results) in enumerate(zip(frames, pp_results_batch)):
            camera_id = camera_ids[i]
            cfg = configs[i]
            
            # Get original frame dimensions for bbox scaling
            orig_h, orig_w = frame.shape[:2]
            
            # Resize frame for visualization
            frame_viz = cv2.resize(frame, TARGET_SIZE, interpolation=cv2.INTER_LINEAR)
            
            # Calculate scale factors for bbox conversion
            scale_x = TARGET_SIZE[0] / orig_w
            scale_y = TARGET_SIZE[1] / orig_h
            
            # Scale bboxes in pp_results
            if hasattr(pp_results, 'boxes') and len(pp_results.boxes) > 0:
                pp_results.boxes = [
                    [int(b[0] * scale_x), int(b[1] * scale_y), int(b[2] * scale_x), int(b[3] * scale_y)]
                    for b in pp_results.boxes
                ]
            
            # Setup Defaults
            features = cfg.get("features", []) if cfg else ["face", "line_crossing", "intrusion"]
            zones = cfg.get("zones", {}) if cfg else {}
            
            # DEBUG: Log Config ONCE per camera ID
            if not hasattr(self, "logged_cameras"): self.logged_cameras = set()
            if camera_id not in self.logged_cameras:
                 print(f"DEBUG-CONFIG [{camera_id}] Features: {features} Zones: {list(zones.keys())}", flush=True)
                 if zones:
                     print(f"DEBUG-CONFIG [{camera_id}] Zone Details: {zones}", flush=True)
                 self.logged_cameras.add(camera_id)

            # --- Spatial Setup (Same as before) ---
            if not hasattr(self, "spatial_map"):
                self.spatial_map = {}
            if camera_id not in self.spatial_map:
                self.spatial_map = {}
            if camera_id not in self.spatial_map:
                 from .spatial import SpatialAnalytics
                 self.spatial_map[camera_id] = SpatialAnalytics()
            
            spatial_cam = self.spatial_map[camera_id]
            
            # Update Spatial Config
            intrusion_classes = config.DEFAULT_INTRUSION_CLASSES
            line_classes = config.DEFAULT_LINE_CROSSING_CLASSES
            
            icfg = cfg.get("intrusion_config") if cfg else None
            if icfg:
                 intrusion_classes = icfg.get("classes", config.DEFAULT_INTRUSION_CLASSES)
            
            # --- VEHICLE RESULTS (Handled in main loop below) ---
        # The previous vehicle_model logic was redundant. 
        # Visualization and Event detection is now integrated into the results loop below.
        # --- END VEHICLE RESULTS ---

            # Use configs[i] which is already defined at this scope (was: cfg = config_data which was undefined)
            # cfg is already set at line 355, so we just continue using it
            lcfg = cfg.get("line_crossing_config") if cfg else None
            if lcfg:
                 line_classes = lcfg.get("classes", config.DEFAULT_LINE_CROSSING_CLASSES)
            
            spatial_cam.set_classes(intrusion_classes, line_classes)
            
            # TEST: Inject zones for specific camera (User Request)
            if camera_id == "ee7433b9-d6e1-41f2-bc92-ae931e884d4c":
                 if "intrusion" not in features: features.append("intrusion")
                 if "line_crossing" not in features: features.append("line_crossing")
                 
                 # Define Test Zones (Normalized to 640x640 usually, but input here is likely relative or absolute)
                 # The set_polygon_zone handles scaling if > 1.5. 
                 # Let's use relative [0-1] to be safe and independent of resolution.
                 
                 # Intrusion: Center Area
                 if "intrusion" not in zones:
                     zones["intrusion"] = {
                         "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]
                     }
                 
                 # Line: Horizontal across
                 if "line_crossing" not in zones:
                     zones["line_crossing"] = {
                         "points": [[0.1, 0.5], [0.9, 0.5]],
                         "trigger": "in_out"
                     }

            # Use TARGET_SIZE for spatial zones since frame_viz is resized
            if "line_crossing" in features and "line_crossing" in zones and zones["line_crossing"]:
                 spatial_cam.set_line_zone(zones["line_crossing"].get("points", []), zones["line_crossing"].get("trigger", "in_out"), TARGET_SIZE)
            if "intrusion" in features and "intrusion" in zones and zones["intrusion"]:
                 spatial_cam.set_polygon_zone(zones["intrusion"].get("points", []), TARGET_SIZE)

            # Update Tracker & Spatial Analysis (using resized frame)
            # pp_results has .boxes, .cls, .id, and tracked objects
            result = spatial_cam.update(frame_viz, pp_results)
            annotated_frame = result.annotated_frame
            
            # --- PP-Human Action Recognition (Fight/Fall) ---
            # Check for generic action events
            if hasattr(pp_results, 'actions') and pp_results.actions:
                # actions dict: {track_id: (label, score)} or {track_id: label}
                current_time = time.time()
                for tid, action_val in pp_results.actions.items():
                    # Handle tuple vs string
                    action = action_val
                    score = 1.0
                    if isinstance(action_val, (tuple, list)):
                        action = action_val[0]
                        score = float(action_val[1])

                    # Map action to event_type
                    event_type = None
                    if action == "fighting": event_type = "fight_detection"
                    elif action == "falling": event_type = "fall_detection"
                    elif action == "smoking": event_type = "compliance_smoking"
                    elif action in ["calling", "phoning"]: event_type = "compliance_calling"
                    
                    if event_type:
                        # CHECK: Is this feature enabled for this camera?
                        if event_type not in features:
                            continue

                        # Debounce (5s)
                        if not hasattr(self, "action_cooldowns"): self.action_cooldowns = {}
                        if camera_id not in self.action_cooldowns: self.action_cooldowns[camera_id] = {}
                        
                        last = self.action_cooldowns[camera_id].get(event_type, 0)
                        if (current_time - last) > 5.0:
                            print(f"🚨 ACTION DETECTION [{camera_id}]: {action.upper()} 🚨")
                            self.save_event_async(camera_id, event_type, str(tid), severity="CRITICAL")
                            self.action_cooldowns[camera_id][event_type] = current_time
                            
                            if self.publish_callback:
                                self.publish_callback("events.alarm", {
                                    "camera_id": camera_id,
                                    "event_type": event_type,
                                    "track_id": str(tid),
                                    "severity": "CRITICAL",
                                    "timestamp": current_time,
                                    "message": f"Action Detected: {action.upper()}"
                                })
                            
                            # Visual Alert on Frame
                            # cv2.putText(annotated_frame, f"ACTION: {action.upper()}", (50, 50), 
                            #             cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 4)
            
            # --- Global Events (e.g. Video Fight Detection) ---
            if hasattr(pp_results, 'global_events') and pp_results.global_events:
                for event in pp_results.global_events:
                     # e.g. "fight_detection"
                     if "fight_detection" == event:
                          # Check debounce
                          if not hasattr(self, "action_cooldowns"): self.action_cooldowns = {}
                          if camera_id not in self.action_cooldowns: self.action_cooldowns[camera_id] = {}
                          last = self.action_cooldowns[camera_id].get("fight_detection", 0)
                          
                          current_time = time.time()
                          if (current_time - last) > 5.0:
                              print(f"🚨 GLOBAL ACTION ALERT [{camera_id}]: FIGHT DETECTED 🚨")
                              self.save_event_async(camera_id, "fight_detection", "global", severity="CRITICAL")
                              self.action_cooldowns[camera_id]["fight_detection"] = current_time
                              
                              if self.publish_callback:
                                  self.publish_callback("events.alarm", {
                                      "camera_id": camera_id,
                                      "event_type": "fight_detection",
                                      "track_id": "global",
                                      "severity": "CRITICAL",
                                      "timestamp": current_time,
                                      "message": "Fight Detected (Video Analysis)"
                                  })
                              
                              # cv2.putText(annotated_frame, "FIGHT DETECTED", (50, 100), 
                              #            cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 4)

            # --- ReID Processing (Forensic Search) ---
            if hasattr(pp_results, 'reid_features') and pp_results.reid_features:
                 # Log feature extraction (Implementation for forensic DB would go here)
                 # For now, we just acknowledge availability
                 # keys are track_ids, values are embeddings
                 pass 
                 # print(f"DEBUG: Extracted ReID features for {len(pp_results.reid_features)} tracks", flush=True)
            
            # --- Logic & Visualization ---
            
            # A. Line Crossing
            # A. Line Crossing
            if "line_crossing" in features:
                in_c, out_c = result.line_counts
                # REMOVED: Manual text overlay ("filter") as requested
                # cv2.putText(annotated_frame, f"In: {in_c} Out: {out_c}", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                
                # Async Stats Save
                if not hasattr(self, "last_save_time"): self.last_save_time = {}
                now = time.time()
                if (now - self.last_save_time.get(camera_id, 0)) > (8 * 3600):
                    self.db.save_stats(camera_id, in_c, out_c) # Non-blocking now
                    self.last_save_time[camera_id] = now

            # B. Intrusion
            if "intrusion" in features and result.intrusion_events:
                 if not hasattr(self, "alert_cooldowns"): self.alert_cooldowns = {}
                 if camera_id not in self.alert_cooldowns: self.alert_cooldowns[camera_id] = {}
                 
                 debounce = config.DEFAULT_INTRUSION_DEBOUNCE
                 icfg = cfg.get("intrusion_config") if cfg else None
                 if icfg:
                     debounce = float(icfg.get("debounce", config.DEFAULT_INTRUSION_DEBOUNCE))
                 
                 curr_time = time.time()
                 
                 for tid in result.intrusion_events:
                     last = self.alert_cooldowns[camera_id].get(tid, 0)
                     if last == 0 or (curr_time - last) > debounce:
                         print(f"🚨 ALERT [{camera_id}]: Intrusion! 🚨")
                         self.save_event_async(camera_id, "intrusion", tid, severity="HIGH") # Non-blocking
                         self.alert_cooldowns[camera_id][tid] = curr_time
                         
                         # Real-Time Notification
                         if self.publish_callback:
                             self.publish_callback("events.alarm", {
                                 "camera_id": camera_id,
                                 "event_type": "intrusion",
                                 "track_id": str(tid),
                                 "severity": "HIGH",
                                 "timestamp": curr_time,
                                 "message": f"Intrusion detected on {camera_id}"
                             })
                 
                 # cv2.putText(annotated_frame, "INTRUSION DETECTED!", (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)

            # C. Face Recognition (Visualization Disabled for Logic Verify)
            if "face" in features:
                processed_any_face = False
                faces_data = face_results_map[i]
                for (bbox, name, color) in faces_data:
                    # Logic Check Log
                    processed_any_face = True
                    # cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                    # cv2.putText(annotated_frame, name, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                
                if processed_any_face:
                     # Log one of the faces for verification
                     n = faces_data[0][1]
                     print(f"🔍 Face Logic Verify [{camera_id}]: Recognized '{n}'", flush=True)



            # Store Metadata for this frame (Normalized 0-1)
            # Frame is already resized to TARGET_SIZE (640x640) for viz, but detections in 'pp_results' 
            # were scaled to this TARGET_SIZE in lines 360-365.
            # So we use TARGET_SIZE to normalize.
            t_w, t_h = TARGET_SIZE

            frame_meta = {
                "camera_id": camera_id,
                "timestamp": time.time(),
                "faces": [],
                "vehicles": [],
                "persons": [], # Added for frontend visualization
                "zones": { # Static data (polygons)
                    "intrusion": [], 
                    "line_crossing": []
                }
            }

            # Add Zones (Normalized)
            if "intrusion" in features and "intrusion" in zones:
                 poly = zones["intrusion"].get("points", [])
                 # Poly is list of [x,y] (likely relative 0-1 or absolute?)
                 # Standard in this project seems to be 0-1 for config? 
                 # Let's assume config is 0-1 as per standard SpatialAnalytics.
                 # If config is 0-1, pass directly.
                 frame_meta["zones"]["intrusion"] = poly
                 
            if "line_crossing" in features and "line_crossing" in zones:
                 line = zones["line_crossing"].get("points", [])
                 frame_meta["zones"]["line_crossing"] = line

            # Add Face Data
            if "face" in features:
                faces_data = face_results_map[i]
                for (bbox, name, color) in faces_data:
                     # bbox is absolute (x1, y1, x2, y2) relative to ORIGINAL FRAME
                     h_orig, w_orig = frames[i].shape[:2]
                     nx1, ny1, nx2, ny2 = bbox[0]/w_orig, bbox[1]/h_orig, bbox[2]/w_orig, bbox[3]/h_orig
                     frame_meta["faces"].append({
                         "bbox": [nx1, ny1, nx2, ny2], 
                         "name": name
                     })

            # Add Vehicle Data
            if i < len(pp_vehicle_results):
                 veh_res = pp_vehicle_results[i]
                 if hasattr(veh_res, 'boxes'):
                     for k, bbox in enumerate(veh_res.boxes):
                         cls_id = int(veh_res.cls[k])
                         score = float(veh_res.conf[k])
                         bx1, by1, bx2, by2 = map(int, bbox)
                         
                         # Normalize
                         nbx1, nby1, nbx2, nby2 = bx1/t_w, by1/t_h, bx2/t_w, by2/t_h
                         
                         label = "Vehicle"
                         if cls_id == 0: label = "Car"
                         elif cls_id == 1: label = "Truck"
                         elif cls_id == 2: label = "Bus"
                         elif cls_id == 3: label = "Moto"
                         
                         plate = None
                         if hasattr(veh_res, 'plates') and veh_res.plates:
                             plate = veh_res.plates.get(k)
                             
                         # Attributes (Color, Type)
                         attrs = None
                         if hasattr(veh_res, 'attributes') and veh_res.attributes:
                             raw_attr = veh_res.attributes.get(k)
                             if raw_attr:
                                 if isinstance(raw_attr, (tuple, list)) and len(raw_attr) >= 2:
                                     attrs = {"color": raw_attr[0], "type": raw_attr[1]}
                                 else:
                                     attrs = {"raw": str(raw_attr)}
                             
                         frame_meta["vehicles"].append({
                            "bbox": [nbx1, nby1, nbx2, nby2],
                            "label": label,
                            "lpr": plate,
                            "score": score,
                            "attributes": attrs
                        })

            # Add Person Data (Generic Object Detection)
            if hasattr(pp_results, 'boxes'):
                 lpr_tasks = [] # Initialize task list for this frame
                 for k, bbox in enumerate(pp_results.boxes):
                     # cls and conf might be tensors or numpy arrays, ensure float/int conversion
                     # PP-Human results structure check:
                     # .boxes is list of [x1, y1, x2, y2]
                     # .cls is list of class IDs
                     # .conf is list of scores
                     
                     try:
                         cls_id = int(pp_results.cls[k])
                         score = float(pp_results.conf[k])
                         print(f"🕵️ DEBUG DET: cls_id={cls_id} score={score:.4f}", flush=True)

                         if cls_id == 0: # person
                             bx1, by1, bx2, by2 = map(int, bbox)
                             
                             # Normalize using TARGET_SIZE (since pp_results.boxes were scaled to TARGET_SIZE in line 365)
                             # Ensure coordinates are within bounds
                             nbx1 = max(0, min(1, bx1 / t_w))
                             nby1 = max(0, min(1, by1 / t_h))
                             nbx2 = max(0, min(1, bx2 / t_w))
                             nby2 = max(0, min(1, by2 / t_h))
                             
                             
                             # Get Track ID if available
                             tid = None
                             if hasattr(pp_results, 'id') and k < len(pp_results.id):
                                 tid = pp_results.id[k]

                             # Retrieve Attributes & ReID
                             attrs = pp_results.attributes.get(tid) if tid is not None else None
                             reid_emb = pp_results.reid.get(tid) if tid is not None and hasattr(pp_results, 'reid') else None
                             
                             # Simplify ReID for metadata (too large to send raw vector)
                             reid_hash = None
                             if reid_emb is not None:
                                 # Simple hash or truncate for ID matching
                                 reid_hash = str(hash(reid_emb.tobytes()) % 1000000)

                             frame_meta["persons"].append({
                                 "bbox": [nbx1, nby1, nbx2, nby2],
                                 "score": score,
                                 "track_id": tid,
                                 "attributes": attrs,
                                 "reid_id": reid_hash
                             })
                             
                         elif cls_id in [1, 2, 3, 5, 7]: # Vehicles (Bike, Car, Moto, Bus, Truck)
                             bx1, by1, bx2, by2 = map(int, bbox)
                             nbx1 = max(0, min(1, bx1 / t_w))
                             nby1 = max(0, min(1, by1 / t_h))
                             nbx2 = max(0, min(1, bx2 / t_w))
                             nby2 = max(0, min(1, by2 / t_h))
                             
                             label = "Vehicle"
                             if cls_id == 1: label = "Bicycle"
                             elif cls_id == 2: label = "Car"
                             elif cls_id == 3: label = "Moto"
                             elif cls_id == 5: label = "Bus"
                             elif cls_id == 7: label = "Truck"

                             # Prepare LPR Data (defer execution)
                             plate_text = None
                             
                             # LPR Optimization: Cache Check
                             should_run_lpr = False
                             if self.lpr_model and "lpr" in features:
                                 should_run_lpr = True
                                 if tid: # Only if tracked
                                     if not hasattr(self, "lpr_results_cache"): self.lpr_results_cache = {}
                                     last_cache = self.lpr_results_cache.get(tid)
                                     if last_cache:
                                         ts, cached_plate = last_cache
                                         if (time.time() - ts) < 3.0: # 3s Cache
                                            should_run_lpr = False
                                            plate_text = cached_plate # Use cached result
                                 
                             if should_run_lpr:
                                  try:
                                      # Scale to original resolution
                                      scale_x_inv = orig_w / t_w
                                      scale_y_inv = orig_h / t_h
                                      vx1 = int(max(0, min(bx1 * scale_x_inv, orig_w)))
                                      vy1 = int(max(0, min(by1 * scale_y_inv, orig_h)))
                                      vx2 = int(max(0, min(bx2 * scale_x_inv, orig_w)))
                                      vy2 = int(max(0, min(by2 * scale_y_inv, orig_h)))
                                      
                                      if (vx2 - vx1) > 50 and (vy2 - vy1) > 50:
                                          vehicle_crop = frame[vy1:vy2, vx1:vx2]
                                          lpr_tasks.append({
                                              'crop': vehicle_crop,
                                              'meta_idx': len(frame_meta["vehicles"]), # Index in the current list
                                              'frame_meta_ref': frame_meta["vehicles"], # Reference to list
                                              'label': label,
                                              'score': score,
                                              'bbox': [bx1, by1, bx2, by2], # Original scale bbox for event
                                              'cam_id': camera_id,
                                              'tid': tid
                                          })
                                  except Exception as e:
                                      pass

                             frame_meta["vehicles"].append({
                                 "bbox": [nbx1, nby1, nbx2, nby2],
                                 "label": label,
                                 "lpr": plate_text, # Will fill later if task runs, or cached
                                 "score": score
                             })
                     except Exception as e:
                         pass

            # --- Execute Parallel LPR for this frame ---
            if lpr_tasks:
                futures = {self.lpr_executor.submit(self.lpr_model.predict, t['crop']): t for t in lpr_tasks}
                for future in concurrent.futures.as_completed(futures):
                    t = futures[future]
                    try:
                        lpr_result = future.result()
                        if lpr_result.label:
                            plate_text = lpr_result.label
                            # Update Frame Meta
                            t['frame_meta_ref'][t['meta_idx']]['lpr'] = plate_text
                            
                            # Update Cache
                            if t.get('tid'):
                                if not hasattr(self, "lpr_results_cache"): self.lpr_results_cache = {}
                                self.lpr_results_cache[t['tid']] = (time.time(), plate_text) # Use plate_text here
                            
                            print(f"🈯 Plate Detected: {plate_text} on {t['label']}", flush=True)

                            # Event Logic
                            curr_t = time.time()
                            if not hasattr(self, 'lpr_cooldowns'): self.lpr_cooldowns = {}
                            cid = t['cam_id']
                            if cid not in self.lpr_cooldowns: self.lpr_cooldowns[cid] = {}
                            
                            last_lpr = self.lpr_cooldowns[cid].get(plate_text, 0)
                            if (curr_t - last_lpr) > 10.0:
                                self.save_event_async(
                                    cid,
                                    "lpr",
                                    plate_text,
                                    confidence=float(t['score']),
                                    bbox=t['bbox'],
                                    severity="INFO"
                                )
                                self.lpr_cooldowns[cid][plate_text] = curr_t
                    except Exception as e:
                        print(f"LPR Future Error: {e}")

            batch_metadata.append(frame_meta)

            processed_frames.append(annotated_frame)

        return processed_frames, batch_metadata

    def process(self, frame, camera_id=None, config=None):
        # Wrapper for single frame
        frames, meta = self.process_batch([frame], [camera_id], [config])
        return frames[0]

    # _draw_yolo_results removed as it is replaced by SpatialAnalytics visualization


