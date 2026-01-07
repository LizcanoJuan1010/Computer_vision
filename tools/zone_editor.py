import cv2
import json
import os
import sys
import numpy as np

# Path to cameras.json
CAMERAS_FILE = "ingest/cameras.json"

class ZoneEditor:
    def __init__(self, camera_config):
        self.camera = camera_config
        self.url = self.resolve_url(camera_config['url'])
        self.cap = cv2.VideoCapture(self.url)
        
        if not self.cap.isOpened():
            print(f"Error: Could not open video source {self.url}")
            sys.exit(1)

        # State
        self.mode = "view" # view, line, polygon
        self.current_points = []
        self.zones = camera_config.get("zones", {})
        
        # Load existing zones if any
        if "line_crossing" not in self.zones:
            self.zones["line_crossing"] = {"points": [], "trigger": "in_out"}
        if "intrusion" not in self.zones:
            self.zones["intrusion"] = {"points": [], "trigger": "enter"}

        # Window
        self.window_name = f"Zone Editor - {camera_config['id']}"
        cv2.namedWindow(self.window_name)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)

    def resolve_url(self, url):
        # 1. Substitute Environment Variables
        # This matches the logic in Go/Ingest to allow {USER}, {PASS} etc.
        replacements = {
            "{USER}": os.getenv("HIK_USER", ""),
            "{PASS}": os.getenv("HIK_PASS", ""),
            "{IP}":   os.getenv("HIK_IP", ""),
            "{PORT_RTSP}": os.getenv("PORT_RTSP", "554"),
            "{PORT_HTTP}": os.getenv("PORT_HTTP", "8080"),
        }
        for key, val in replacements.items():
            if val:
                url = url.replace(key, val)

        # 2. Handle local file paths relative to project root
        if url.startswith("/"):
             # Assuming running from project root
             if os.path.exists("." + url):
                 return "." + url
             # If it's an absolute path in the container but we are on host
             # Try to find it in ingest/ directory if it's a test video
             if url == "/test_video.mp4" and os.path.exists("ingest/test_video.mp4"):
                 return "ingest/test_video.mp4"
        return url

    def mouse_callback(self, event, x, y, flags, param):
        if self.mode == "view":
            return

        if event == cv2.EVENT_LBUTTONDOWN:
            self.current_points.append([x, y])
            print(f"Point added: ({x}, {y})")

    def save_config(self):
        # Read current file to avoid overwriting other changes
        with open(CAMERAS_FILE, 'r') as f:
            all_cameras = json.load(f)
        
        # Update specific camera
        for cam in all_cameras:
            if cam['id'] == self.camera['id']:
                cam['zones'] = self.zones
                # Ensure features list exists
                if "features" not in cam:
                    cam["features"] = ["face", "line_crossing", "intrusion"]
                break
        
        with open(CAMERAS_FILE, 'w') as f:
            json.dump(all_cameras, f, indent=4)
        print(f"Configuration saved to {CAMERAS_FILE}")

    def run(self):
        print("--- Controls ---")
        print("IMPORTANT: Click on the VIDEO WINDOW before pressing keys!")
        print("L: Draw Line (Click multiple points, Enter to finish)")
        print("P: Draw Polygon (Click points, Enter to finish)")
        print("Z: Undo last point")
        print("C: Clear current drawing")
        print("S: Save Configuration")
        print("Q: Quit")
        
        saved_message_timer = 0
        
        while True:
            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0) # Loop video
                continue

            # --- Letterbox Resize (Match Ingest Logic) ---
            # Target dimensions
            target_w = int(os.getenv("RESIZE_WIDTH", 640))
            target_h = int(os.getenv("RESIZE_HEIGHT", 360))

            h, w = frame.shape[:2]
            scale = min(target_w / w, target_h / h)
            nw, nh = int(w * scale), int(h * scale)

            # Resize content
            resized_inner = cv2.resize(frame, (nw, nh))

            # Create canvas (grey background like ingest)
            canvas = np.full((target_h, target_w, 3), 128, dtype=np.uint8)
            
            # Center offsets
            x_off = (target_w - nw) // 2
            y_off = (target_h - nh) // 2

            # Place image
            canvas[y_off:y_off+nh, x_off:x_off+nw] = resized_inner
            frame = canvas
            # ---------------------------------------------

            # Draw existing zones
            # Line (Polyline)
            line_pts = self.zones.get("line_crossing", {}).get("points", [])
            if len(line_pts) >= 2:
                pts = np.array(line_pts, np.int32)
                pts = pts.reshape((-1, 1, 2))
                cv2.polylines(frame, [pts], False, (0, 255, 0), 2)
                cv2.putText(frame, "Line Zone (Active)", tuple(line_pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # Polygon
            poly_pts = self.zones.get("intrusion", {}).get("points", [])
            if len(poly_pts) > 2:
                pts = np.array(poly_pts, np.int32)
                pts = pts.reshape((-1, 1, 2))
                cv2.polylines(frame, [pts], True, (0, 0, 255), 2)
                cv2.putText(frame, "Intrusion Zone (Active)", tuple(poly_pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            # Draw current drawing
            if self.mode != "view" and len(self.current_points) > 0:
                for pt in self.current_points:
                    cv2.circle(frame, tuple(pt), 5, (255, 255, 0), -1)
                
                if len(self.current_points) > 1:
                    # Draw as polyline for both modes while drawing
                    pts = np.array(self.current_points, np.int32).reshape((-1, 1, 2))
                    cv2.polylines(frame, [pts], False, (255, 255, 0), 1)

            # UI Overlay - Instructions
            y_offset = 30
            cv2.putText(frame, f"Mode: {self.mode.upper()}", (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            y_offset += 30
            
            if self.mode == "view":
                cv2.putText(frame, "[L] Line | [P] Polygon | [S] Save | [Q] Quit", (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            else:
                cv2.putText(frame, f"Points: {len(self.current_points)}", (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                y_offset += 25
                cv2.putText(frame, "[Click] Add Point | [Z] Undo | [Enter] Finish | [C] Cancel", (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

            # Saved Feedback
            if saved_message_timer > 0:
                cv2.putText(frame, "CONFIGURATION SAVED!", (frame.shape[1]//2 - 150, frame.shape[0]//2), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)
                saved_message_timer -= 1

            cv2.imshow(self.window_name, frame)
            
            key = cv2.waitKey(30) & 0xFF
            
            if key == ord('q'):
                break
            elif key == ord('l'): # L - Line Mode
                self.mode = "line"
                self.current_points = []
                print("Mode: Draw Line. Click multiple points. Press 'Enter' to finish.")
            elif key == ord('p'): # P - Polygon Mode
                self.mode = "polygon"
                self.current_points = []
                print("Mode: Draw Polygon. Click points. Press 'Enter' to finish.")
            elif key == ord('c'): # C - Clear/Cancel
                self.current_points = []
                self.mode = "view"
                print("Cancelled drawing.")
            elif key == ord('z'): # Z - Undo
                if len(self.current_points) > 0:
                    self.current_points.pop()
                    print("Undo last point.")
            elif key == ord('s'): # S - Save
                self.save_config()
                saved_message_timer = 30 # Show message for ~1 second (30 frames)
            elif key == 13: # Enter key
                if self.mode == "line":
                    if len(self.current_points) >= 2:
                        self.zones["line_crossing"]["points"] = self.current_points
                        print("Line Zone Updated.")
                        self.mode = "view"
                        self.current_points = []
                    else:
                        print("Need at least 2 points for a line.")
                elif self.mode == "polygon":
                    if len(self.current_points) > 2:
                        self.zones["intrusion"]["points"] = self.current_points
                        print("Intrusion Zone Updated.")
                        self.mode = "view"
                        self.current_points = []
                    else:
                        print("Need at least 3 points for a polygon.")

        self.cap.release()
        cv2.destroyAllWindows()

def main():
    if not os.path.exists(CAMERAS_FILE):
        print(f"Error: {CAMERAS_FILE} not found.")
        return

    with open(CAMERAS_FILE, 'r') as f:
        cameras = json.load(f)

    print("Select a camera to edit:")
    for i, cam in enumerate(cameras):
        print(f"{i + 1}. {cam['id']} ({cam['url']})")

    try:
        choice = int(input("Enter number: ")) - 1
        if 0 <= choice < len(cameras):
            editor = ZoneEditor(cameras[choice])
            editor.run()
        else:
            print("Invalid selection.")
    except ValueError:
        print("Invalid input.")

if __name__ == "__main__":
    main()
