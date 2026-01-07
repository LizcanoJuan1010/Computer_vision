import cv2
import time
from ..config import config
from .core import BaseProcessor

from .spatial import SpatialAnalytics

class SecurityProcessor(BaseProcessor):
    def __init__(self, db, yolo_model, face_model, lpr_model, face_cache=None, publish_callback=None):
        self.db = db
        self.yolo_model = yolo_model
        self.face_model = face_model
        self.lpr_model = lpr_model
        self.face_cache = face_cache  # FaceCacheLFU instance
        self.publish_callback = publish_callback
        # Initialize Spatial Analytics (Tracking, Zones)
        self.spatial = SpatialAnalytics()

        # Performance: Frame Counters for skipping
        self.frame_counter = 0
        self.SKIP_FACTOR = 3 # Run Face/LPR every 5th frame (3 checks/sec at 15 FPS)

    def process_batch(self, frames, camera_ids, configs):
        start_time = time.time()
        
        # --- 1. PP-Human Inference (Batch) ---
        # Run Detection/Tracking/Action on every frame
        pp_results_batch = self.yolo_model.predict(frames) # yolo_model is actually PPHumanModel instance now
        
        # DEBUG: Print detection stats
        for i, res in enumerate(pp_results_batch):
             if len(res.boxes) > 0:
                 print(f"[{camera_ids[i]}] Detectados: {len(res.boxes)} personas/objetos", flush=True)
        
        # Increment counter
        self.frame_counter += 1
        run_heavy_models = (self.frame_counter % self.SKIP_FACTOR == 0)

        # --- 2. Prepare Face Recognition Batch (skipped if not heavy frame) ---
        face_crops = []
        face_metadata = [] # (batch_index, detection_index_in_frame, bbox)

        if run_heavy_models:
             for i, (frame, pp_results) in enumerate(zip(frames, pp_results_batch)):
                 config_data = configs[i]
                 features = config_data.get("features", []) if config_data else ["face", "line_crossing", "intrusion"]
                 
                 if "face" in features:
                     # Find persons
                     # PP-Result wrapper should have iterate-able boxes
                     # Assuming pp_results.boxes is list of xyxy, and cls is list of class_ids
                     if hasattr(pp_results, 'boxes'):
                         for j, bbox_raw in enumerate(pp_results.boxes):
                             cls_id = int(pp_results.cls[j]) if len(pp_results.cls) > j else 0
                             if cls_id == 0: # Person
                                 x1, y1, x2, y2 = bbox_raw
                                 # Clip
                                 h, w = frame.shape[:2]
                                 x1, y1 = max(0, int(x1)), max(0, int(y1))
                                 x2, y2 = min(w, int(x2)), min(h, int(y2))
                                 
                                 if x2 > x1 and y2 > y1:
                                     face_crop = frame[y1:y2, x1:x2]
                                     face_crops.append(face_crop)
                                     face_metadata.append((i, j, (x1, y1, x2, y2)))

        # --- 3. Batch Face Recognition ---
        # Initialize face_results map: {batch_index: [ (bbox, name, color) ] }
        face_results_map = {i: [] for i in range(len(frames))}
        
        if face_crops:
            # Predict all faces at once
            all_faces_analysis = self.face_model.predict(face_crops)
            
            # Re-map results
            for k, faces in enumerate(all_faces_analysis):
                # faces is a list of Face objects found in the crop
                if not faces:
                    continue
                
                # Sort by size
                faces = sorted(faces, key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]), reverse=True)
                primary_face = faces[0]
                
                # Identify
                batch_idx, det_idx, crop_bbox = face_metadata[k]
                cx1, cy1, cx2, cy2 = crop_bbox

                # Config threshold
                cfg_data = configs[batch_idx]
                threshold = config.SIMILARITY_THRESHOLD

                # Safe check for face_config
                face_cfg = cfg_data.get("face_config") if cfg_data else None
                if face_cfg and "threshold" in face_cfg:
                    threshold = float(face_cfg["threshold"])

                # Get org_id from config (needed for cache search)
                org_id = cfg_data.get("org_id") if cfg_data else None

                # Search using FaceCacheLFU (Hybrid L1+L2)
                match = None
                is_from_global = False

                if self.face_cache and org_id:
                    # Use cache (< 1ms search in L1)
                    import asyncio
                    match = asyncio.run(self.face_cache.search(
                        query_embedding=primary_face.embedding,
                        org_id=org_id,
                        threshold=threshold,
                        include_global_blacklist=True
                    ))
                    if match:
                        face_id, name, category, similarity, is_from_global = match
                else:
                    # Fallback to database search (old method)
                    db_match = self.db.find_nearest_face(primary_face.embedding)
                    if db_match:
                        db_name, distance = db_match
                        req_dist = 1.0 - threshold
                        if distance < req_dist:
                            match = (None, db_name, 'KNOWN', 1.0 - distance, False)

                # Determine name and color
                if match:
                    _, name, category, similarity, is_from_global = match

                    # Color coding
                    if category == 'BLACKLIST':
                        color = (0, 0, 255) if not is_from_global else (255, 0, 255)  # Red or Magenta (global)
                        # Alert for blacklist detection
                        if self.publish_callback:
                            self.publish_callback("events.face.blacklist", {
                                "camera_id": camera_ids[batch_idx],
                                "name": name,
                                "category": category,
                                "similarity": float(similarity),
                                "is_global_blacklist": is_from_global,
                                "timestamp": time.time()
                            })
                    elif category == 'KNOWN':
                        color = (0, 255, 0)  # Green
                    else:  # UNKNOWN
                        color = (255, 255, 0)  # Yellow
                    
                    # --- SAVE FACE EVENT TO DB (With Debounce) ---
                    # We save 'face_recognition' events. track_id = name.
                    curr_time = time.time()
                    if not hasattr(self, "face_alert_cooldowns"): self.face_alert_cooldowns = {}
                    if camera_ids[batch_idx] not in self.face_alert_cooldowns: self.face_alert_cooldowns[camera_ids[batch_idx]] = {}
                    
                    # Debounce key: name + category
                    debounce_key = f"{name}_{category}"
                    last_face_alert = self.face_alert_cooldowns[camera_ids[batch_idx]].get(debounce_key, 0)
                    
                    # 5 Second Debounce for same face
                    if (curr_time - last_face_alert) > 5.0: 
                        severity = "HIGH" if category == 'BLACKLIST' else "INFO"
                        self.db.save_event(
                            camera_ids[batch_idx], 
                            "face_recognition", 
                            name, # track_id is the Name
                            confidence=float(similarity),
                            bbox=abs_box,
                            severity=severity
                        )
                        self.face_alert_cooldowns[camera_ids[batch_idx]][debounce_key] = curr_time
                        # print(f"Saved Face Event: {name} ({category})")

                else:
                    name = "Unknown"
                    color = (0, 0, 255)  # Red for unrecognized

                    # --- AUTO-SAVE UNKNOWN IN RESTRICTED ZONES ---
                    is_restricted = cfg_data.get("is_restricted_zone", False) if cfg_data else False
                    auto_save = cfg_data.get("auto_save_unknown", False) if cfg_data else False

                    if is_restricted and auto_save and org_id:
                         # Debounce per camera (5 seconds)
                         curr_time = time.time()
                         if not hasattr(self, "unknown_save_cooldown"): self.unknown_save_cooldown = {}
                         last_save = self.unknown_save_cooldown.get(camera_ids[batch_idx], 0)
                         
                         if (curr_time - last_save) > 5.0:
                              try:
                                  # Generate Name
                                  timestamp = int(curr_time)
                                  auto_name = f"Unknown_{timestamp}"
                                  
                                  # Insert into DB
                                  self.db.cur.execute("""
                                      INSERT INTO faces (name, embedding, organization_id, category, meta_info) 
                                      VALUES (%s, %s, %s, 'UNKNOWN', '{"auto_saved": true}')
                                  """, (auto_name, primary_face.embedding.tolist(), org_id))
                                  self.db.conn.commit()
                                  
                                  self.unknown_save_cooldown[camera_ids[batch_idx]] = curr_time
                                  print(f"🚨 Auto-saved UNKNOWN face in restricted zone: {auto_name}")
                                  
                                  # Helper: Trigger High Severity Alert
                                  if self.publish_callback:
                                      self.publish_callback("events.alarm", {
                                          "camera_id": camera_ids[batch_idx],
                                          "event_type": "security_alert",
                                          "severity": "HIGH",
                                          "message": f"Security Breach: Unrecognized person in Restricted Zone"
                                      })
                                      
                              except Exception as e:
                                  print(f"Error auto-saving unknown face: {e}")
                                  self.db.conn.rollback()

                # Store absolute bbox of the Face relative to original frame? 
                fx1, fy1, fx2, fy2 = primary_face.bbox.astype(int)
                abs_box = (cx1 + fx1, cy1 + fy1, cx1 + fx2, cy1 + fy2)
                
                face_results_map[batch_idx].append((abs_box, name, color))

        # --- 3.5 Batch LPR (License Plate Recognition) ---
        lpr_results_map = {i: [] for i in range(len(frames))}
        lpr_frames = []
        lpr_indices = []
        
        if run_heavy_models:
             for i, frame in enumerate(frames):
                 cfg = configs[i]
                 feats = cfg.get("features", []) if cfg else []
                 if "lpr" in feats:
                     lpr_indices.append(i)
                     lpr_frames.append(frame)
        
        if lpr_frames:
             lpr_batch_out = self.lpr_model.predict(lpr_frames, conf=config.DEFAULT_LPR_CONFIDENCE)
             for idx, lpr_res in zip(lpr_indices, lpr_batch_out):
                 # lpr_res is YOLO Result object
                 for box in lpr_res.boxes:
                     x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                     conf = float(box.conf[0])
                     # We assume class 0 is plate, but we accept any detection from this specialized model
                     plate_text = f"Plate: {conf:.2f}" 
                     lpr_results_map[idx].append(((x1, y1, x2, y2), plate_text))
                     
                     # Async Save Event (High Confidence)
                     if conf > 0.6:
                          self.db.save_event(camera_ids[idx], "license_plate", f"plate_detected_{int(time.time())}", severity="INFO")
                          # Real-Time Notification
                          if self.publish_callback:
                              self.publish_callback("events.alarm", {
                                  "camera_id": camera_ids[idx],
                                  "event_type": "license_plate",
                                  "plate_text": plate_text,
                                  "severity": "INFO",
                                  "timestamp": time.time(),
                                  "message": f"License Plate {plate_text} detected"
                              })

        # --- 4. Spatial Analysis & Visualization (Per Frame) ---
        processed_frames = []
        
        for i, (frame, pp_results) in enumerate(zip(frames, pp_results_batch)):
            camera_id = camera_ids[i]
            cfg = configs[i]
            
            # Setup Defaults
            features = cfg.get("features", []) if cfg else ["face", "line_crossing", "intrusion"]
            zones = cfg.get("zones", {}) if cfg else {}

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
            
            lcfg = cfg.get("line_crossing_config") if cfg else None
            if lcfg:
                 line_classes = lcfg.get("classes", config.DEFAULT_LINE_CROSSING_CLASSES)
            
            spatial_cam.set_classes(intrusion_classes, line_classes)
            
            if "line_crossing" in features and "line_crossing" in zones and zones["line_crossing"]:
                 spatial_cam.set_line_zone(zones["line_crossing"].get("points", []), zones["line_crossing"].get("trigger", "in_out"), (frame.shape[1], frame.shape[0]))
            if "intrusion" in features and "intrusion" in zones and zones["intrusion"]:
                 spatial_cam.set_polygon_zone(zones["intrusion"].get("points", []), (frame.shape[1], frame.shape[0]))

            # Update Tracker & Spatial Analysis
            # pp_results has .boxes, .cls, .id, and tracked objects
            result = spatial_cam.update(frame, pp_results)
            annotated_frame = result.annotated_frame
            
            # --- PP-Human Action Recognition (Fight/Fall) ---
            # Check for generic action events
            if hasattr(pp_results, 'actions') and pp_results.actions:
                # actions dict: {track_id: "fighting"}
                current_time = time.time()
                for tid, action in pp_results.actions.items():
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
                            self.db.save_event(camera_id, event_type, str(tid), severity="CRITICAL")
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
                            cv2.putText(annotated_frame, f"ACTION: {action.upper()}", (50, 50), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 4)
            
            # --- Logic & Visualization ---
            
            # A. Line Crossing
            if "line_crossing" in features:
                in_c, out_c = result.line_counts
                cv2.putText(annotated_frame, f"In: {in_c} Out: {out_c}", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                
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
                         self.db.save_event(camera_id, "intrusion", tid, severity="HIGH") # Non-blocking
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
                 
                 cv2.putText(annotated_frame, "INTRUSION DETECTED!", (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)

            # C. Face Recognition (Visualization)
            if "face" in features:
                faces_data = face_results_map[i]
                for (bbox, name, color) in faces_data:
                    x1, y1, x2, y2 = bbox
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(annotated_frame, name, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

            # D. LPR Visualization
            if "lpr" in features:
                lpr_res = lpr_results_map[i]
                for ((x1, y1, x2, y2), text) in lpr_res:
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (255, 0, 255), 2) # Magenta
                    cv2.putText(annotated_frame, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)

            processed_frames.append(annotated_frame)

            # D. Headless Check (Only imshow if local)
            import os
            if os.getenv("HEADLESS", "false").lower() != "true":
                try:
                    cv2.imshow(f"VIGIAS-IA - {camera_id}", annotated_frame)
                    cv2.waitKey(1)
                except: pass
                
        return processed_frames

    def process(self, frame, camera_id=None, config=None):
        # Wrapper for single frame
        return self.process_batch([frame], [camera_id], [config])[0]

    # _draw_yolo_results removed as it is replaced by SpatialAnalytics visualization

    def _process_faces(self, frame, faces, config_data=None):
        # Determine Threshold
        threshold = config.SIMILARITY_THRESHOLD
        if config_data and "face_config" in config_data:
             fc = config_data["face_config"]
             if isinstance(fc, dict) and "threshold" in fc:
                 threshold = float(fc["threshold"])

        for face in faces:
            bbox = face.bbox.astype(int)
            embedding = face.embedding
            
            # Search in DB
            match = self.db.find_nearest_face(embedding)
            
            name = "Unknown"
            color = (0, 0, 255) # Red
            
            if match:
                db_name, distance = match
                # distance is cosine distance (0 to 2), usually 0 to 1 for normalized vectors
                # If similarity > threshold => distance < (1 - threshold)? 
                # InsightFace typically returns cosine distance or L2. 
                # Assuming standard cosine distance where smaller is better?
                # Actually arcface/insightface returns similarity score usually or distance?
                # The original code was: distance < (1 - config.SIMILARITY_THRESHOLD)
                # This implies distance is "dissimilarity" (0=same, 1=ortho, 2=opposite).
                # So if we want similarity 0.6, we accept distance < 0.4.
                
                req_dist = 1.0 - threshold
                
                if distance < req_dist:
                    name = db_name
                    color = (0, 255, 0) # Green
            
            # Draw BBox and Name
            cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
            cv2.putText(frame, name, (bbox[0], bbox[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
