from dataclasses import dataclass
from typing import List, Tuple, Any
import cv2
import numpy as np
import supervision as sv

@dataclass
class SpatialResult:
    annotated_frame: np.ndarray
    line_counts: Tuple[int, int] # (in, out)
    intrusion_events: List[int]  # List of Track IDs inside the zone

class SpatialAnalytics:
    """
    Handles Spatial Analytics: Line Crossing and Intrusion Detection.
    Expects detections with Track IDs (provided by PP-Human).
    """
    def __init__(self, width: int = 1280, height: int = 720):
        # Tracker is now handled by the UPSTREAM model (PP-Human)
        # We just consume the IDs.
        
        # 2. Line Crossing (Counter)
        self.line_zones: List[sv.LineZone] = []
        self.line_trigger = "in_out" # Default trigger
        self.line_annotator = sv.LineZoneAnnotator(
            thickness=2,
            text_thickness=1,
            text_scale=0.5
        )

        # 3. Intrusion Detection (Polygon Zone)
        self.polygon_zone = None
        self.polygon_annotator = None 
        
        self.box_annotator = sv.BoxAnnotator(
            thickness=2
        )
        self.label_annotator = sv.LabelAnnotator(
            text_thickness=1,
            text_scale=0.5
        )

        # Store current config
        self.current_line_points = []
        self.current_polygon_points = []
        
        # Configurable Classes (Default: Person=0)
        self.intrusion_classes = [0]
        self.line_crossing_classes = [0]

    def set_line_zone(self, points: List[List[int]], trigger: str = "in_out", frame_wh: Tuple[int, int] = (1280, 720)):
        """Updates the line zone dynamically."""
        if points == self.current_line_points and trigger == self.line_trigger:
            return

        self.current_line_points = points
        self.line_trigger = trigger
        self.line_zones = []

        if len(points) >= 2:
            pts_array = np.array(points)
            current_w, current_h = frame_wh
            max_x = np.max(pts_array[:, 0])
            max_y = np.max(pts_array[:, 1])
            REF_W, REF_H = 1920, 1080
            should_scale = False
            
            if max_x > current_w or max_y > current_h:
                should_scale = True

            if max_x <= 1.5 and max_y <= 1.5:
                 print(f"⚠️ Line: Detected RELATIVE coordinates. Input: {pts_array.tolist()} Scaling to {frame_wh}", flush=True)
                 pts_array = (pts_array * [current_w, current_h]).astype(int)
                 print(f"⚠️ Line: Final Scaled Points: {pts_array.tolist()}", flush=True)
            elif should_scale or (current_w == 1280 and max_x > 1300) or (current_w == 640 and max_x > 700):
                  print(f"⚠️ Line: Scaling from REF 1920x1080 to {frame_wh} (MaxX: {max_x})")
                  scale_x = current_w / REF_W
                  scale_y = current_h / REF_H
                  pts_array = (pts_array * [scale_x, scale_y]).astype(int)
                  pts_array[:, 0] = np.clip(pts_array[:, 0], 0, current_w)
                  pts_array[:, 1] = np.clip(pts_array[:, 1], 0, current_h)
            else:
                  print(f"DEBUG: Line Zone Points Used AS IS (Frame: {frame_wh}, Points: {points})", flush=True)
            
            for i in range(len(pts_array) - 1):
                start = sv.Point(pts_array[i][0], pts_array[i][1])
                end = sv.Point(pts_array[i+1][0], pts_array[i+1][1])
                if start.x == end.x and start.y == end.y: continue
                self.line_zones.append(sv.LineZone(start=start, end=end, triggering_anchors=[sv.Position.BOTTOM_CENTER]))

    def set_polygon_zone(self, points: List[List[int]], frame_wh: Tuple[int, int] = (1280, 720)):
        """Updates the polygon zone dynamically."""
        if points == self.current_polygon_points:
            return

        self.current_polygon_points = points
        
        if len(points) > 2:
            polygon = np.array(points)
            current_w, current_h = frame_wh
            max_x = np.max(polygon[:, 0])
            max_y = np.max(polygon[:, 1])
            REF_W, REF_H = 1920, 1080
            should_scale = False
            
            if max_x > current_w or max_y > current_h: should_scale = True
            
            if max_x <= 1.5 and max_y <= 1.5:
                 # RELATIVE: scale to current resolution
                 print(f"DEBUG: Line/Poly scale RELATIVE {frame_wh}", flush=True)
                 polygon = (polygon * [current_w, current_h]).astype(int)
            else:
                 # ABSOLUTE: Always scale assuming source was 1920x1080 if not close to native
                 # This fixes the issue where small polygons don't trigger "should_scale" logic
                 # but essentially become huge on a downsampled 640x360 stream.
                 if abs(current_w - REF_W) > 100:
                      print(f"DEBUG: Line/Poly scale ABSOLUTE (Ref {REF_W}x{REF_H} -> {current_w}x{current_h})", flush=True)
                      scale_x = current_w / REF_W
                      scale_y = current_h / REF_H
                      polygon = (polygon * [scale_x, scale_y]).astype(int)
                 
                 polygon[:, 0] = np.clip(polygon[:, 0], 0, current_w)
                 polygon[:, 1] = np.clip(polygon[:, 1], 0, current_h)

            self.polygon_zone = sv.PolygonZone(polygon=polygon, frame_resolution_wh=frame_wh)
            self.polygon_annotator = sv.PolygonZoneAnnotator(
                zone=self.polygon_zone, color=sv.Color.RED, thickness=2, text_thickness=1, text_scale=0.5
            )
        else:
            self.polygon_zone = None
            self.polygon_annotator = None

    def set_classes(self, intrusion_classes: List[int] = None, line_crossing_classes: List[int] = None):
        if intrusion_classes is not None: self.intrusion_classes = intrusion_classes
        if line_crossing_classes is not None: self.line_crossing_classes = line_crossing_classes

    def annotate(self, frame: np.ndarray, detections: sv.Detections) -> np.ndarray:
        """
        Draws zones, lines, and annotations on the frame using PIL to avoid SIGILL crashes.
        """
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np

        # 1. Convert to PIL (BGR -> RGB)
        # Check if frame is valid
        if frame is None or frame.size == 0:
            return frame
            
        try:
             # OpenCV is BGR, PIL needs RGB
             frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
             pil_image = Image.fromarray(frame_rgb)
             draw = ImageDraw.Draw(pil_image)
             
             # Load a font (fallback to default if arial unavailable)
             try:
                 font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
             except:
                 font = ImageFont.load_default()

             width, height = pil_image.size

             # 2. Draw Intrusion Zone (Polygon)
             if self.polygon_zone is not None and len(self.current_polygon_points) > 2:
                  # Convert points to flat list of tuples for PIL
                  # self.polygon_zone.polygon is a numpy array [[x,y], [x,y]]
                  poly_points = [tuple(p) for p in self.polygon_zone.polygon]
                  
                  # Draw Polygon (Red outline, semi-transparent fill is hard in PIL simple, just outline for now)
                  draw.polygon(poly_points, outline=(255, 0, 0), width=3)

             # 3. Draw Line Zones
             if self.line_zones:
                 for zone in self.line_zones:
                     # zone.vector is sv.Vector(start=Point(x,y), end=Point(x,y))
                     start = (int(zone.vector.start.x), int(zone.vector.start.y))
                     end = (int(zone.vector.end.x), int(zone.vector.end.y))
                     draw.line([start, end], fill=(255, 255, 0), width=3)
                     
                     # Draw Counts
                     # Calculate mid point
                     mid_x = (start[0] + end[0]) // 2
                     mid_y = (start[1] + end[1]) // 2
                     text = f"In: {zone.in_count} Out: {zone.out_count}"
                     draw.text((mid_x, mid_y), text, fill=(255, 255, 255), font=font)

             # 4. Draw Detections
             labels = []
             for i in range(len(detections)):
                  tid = detections.tracker_id[i] if detections.tracker_id is not None else "N/A"
                  class_id = detections.class_id[i]
                  labels.append(f"#{tid}")

             # Identify Intrusion IDs for coloring
             intrusion_ids = []
             if self.polygon_zone is not None and len(detections) > 0 and detections.tracker_id is not None:
                mask_intrusion_classes = np.isin(detections.class_id, self.intrusion_classes)
                detections_for_intrusion_check = detections[mask_intrusion_classes]
                if len(detections_for_intrusion_check) > 0:
                    is_inside = self.polygon_zone.trigger(detections=detections_for_intrusion_check)
                    if np.any(is_inside):
                        intrusion_ids = detections_for_intrusion_check.tracker_id[is_inside].tolist()
                        
             # Draw Boxes
             for i, xyxy in enumerate(detections.xyxy):
                 x1, y1, x2, y2 = map(int, xyxy)
                 
                 # Clamp
                 x1 = max(0, min(width, x1))
                 y1 = max(0, min(height, y1))
                 x2 = max(0, min(width, x2))
                 y2 = max(0, min(height, y2))
                 
                 tid = detections.tracker_id[i] if detections.tracker_id is not None else None
                 
                 # Color Logic
                 color = (0, 255, 0) # Green (Safe)
                 if tid is not None and tid in intrusion_ids:
                     color = (255, 0, 0) # Red (Intrusion)
                 
                 # 1. Draw Rectangle
                 draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
                 
                 # 2. Draw Label Background & Text
                 label = labels[i]
                 # text_bbox = draw.textbbox((x1, y1), label, font=font) # Requires recent Pillow
                 # Simple rect for text
                 draw.rectangle([x1, y1-20, x1+60, y1], fill=color)
                 draw.text((x1+5, y1-18), label, fill=(255, 255, 255), font=font)

             # Convert back to BGR for OpenCV pipeline
             annotated_numpy = np.array(pil_image)
             annotated_frame = cv2.cvtColor(annotated_numpy, cv2.COLOR_RGB2BGR)
             
             return annotated_frame
             
        except Exception as e:
             print(f"❌ ERROR drawing with PIL: {e}", flush=True)
             return frame


    def update(self, frame: np.ndarray, detections_input: Any) -> SpatialResult:
        """
        Updates zones with new detections (Pre-Tracked).
        detections_input: Can be PPHumanResult or generic object with boxes, conf, cls, id.
        """
        # Convert to Supervision Detections
        # Convert to Supervision Detections
        if hasattr(detections_input, 'boxes') and detections_input.boxes is not None and len(detections_input.boxes) > 0:
            # Check format of boxes
            xyxy = np.array(detections_input.boxes) if isinstance(detections_input.boxes, list) else detections_input.boxes
            confidence = np.array(detections_input.conf) if isinstance(detections_input.conf, list) else detections_input.conf
            class_id = np.array(detections_input.cls).astype(int) if isinstance(detections_input.cls, list) else detections_input.cls
            tracker_id = np.array(detections_input.id).astype(int) if isinstance(detections_input.id, list) else detections_input.id
            
            # If no tracker_id provided (e.g. PP-Human didn't track yet?), provide None
            if tracker_id is None or len(tracker_id) == 0:
                tracker_id = None
            
            detections = sv.Detections(
                xyxy=xyxy,
                confidence=confidence,
                class_id=class_id,
                tracker_id=tracker_id
            )
        else:
            detections = sv.Detections.empty()

        # Filter detections for relevant classes (Union)
        relevant_classes = list(set(self.intrusion_classes + self.line_crossing_classes))
        mask = np.isin(detections.class_id, relevant_classes)
        detections = detections[mask]

        # --- Line Crossing Logic ---
        mask_line = np.isin(detections.class_id, self.line_crossing_classes)
        detections_line = detections[mask_line]

        total_in = 0
        total_out = 0
        
        # Only trigger if we have tracker_id
        if detections.tracker_id is not None and self.line_zones:
            for zone in self.line_zones:
                zone.trigger(detections=detections_line)
                if self.line_trigger == "in_out":
                    total_in += zone.in_count
                    total_out += zone.out_count
                elif self.line_trigger == "in":
                    total_in += zone.in_count
                elif self.line_trigger == "out":
                    total_out += zone.out_count
        
        # --- Intrusion Logic ---
        mask_intrusion = np.isin(detections.class_id, self.intrusion_classes)
        detections_intrusion_logic = detections[mask_intrusion]

        intrusion_ids = []
        if self.polygon_zone is not None:
            is_inside = self.polygon_zone.trigger(detections=detections_intrusion_logic)
            if np.any(is_inside) and detections_intrusion_logic.tracker_id is not None:
                intrusion_ids = detections_intrusion_logic.tracker_id[is_inside].tolist()

        # --- Annotation (Call simplified annotate) ---
        annotated_frame = self.annotate(frame, detections)
        
        return SpatialResult(
            annotated_frame=annotated_frame,
            line_counts=(total_in, total_out),
            intrusion_events=intrusion_ids
        )
