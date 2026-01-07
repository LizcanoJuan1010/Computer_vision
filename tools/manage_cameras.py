
import json
import redis
import os
import sys

# Color Helpers
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")
r = redis.from_url(REDIS_URL, decode_responses=True)

def list_cameras():
    keys = r.keys("config:camera:*")
    if not keys:
        print(f"{Colors.WARNING}No cameras found in Redis.{Colors.ENDC}")
        return []
    
    cameras = []
    print(f"\n{Colors.HEADER}=== Connected Cameras ==={Colors.ENDC}")
    for idx, key in enumerate(sorted(keys)):
        data_str = r.get(key)
        data = json.loads(data_str)
        cam_id = key.split(":")[-1]
        active = data.get("active", False)
        status_color = Colors.GREEN if active else Colors.FAIL
        
        # Determine services/features
        # Router uses "services" list
        services = data.get("services", [])
        
        print(f"{idx + 1}. {Colors.BOLD}{cam_id}{Colors.ENDC} [{status_color}{'ACTIVE' if active else 'INACTIVE'}{Colors.ENDC}]")
        print(f"   Active AIs: {Colors.BLUE}{', '.join(services)}{Colors.ENDC}")
        cameras.append((key, data))
    
    return cameras

def toggle_feature(camera_key, camera_data):
    current_services = camera_data.get("services", [])
    
    available_ais = ["face", "intrusion", "line_crossing", "lpr"]
    
    print(f"\n{Colors.HEADER}--- Manage AI for {camera_key.split(':')[-1]} ---{Colors.ENDC}")
    for idx, ai in enumerate(available_ais):
        status = "ON" if ai in current_services else "OFF"
        color = Colors.GREEN if status == "ON" else Colors.FAIL
        print(f"{idx + 1}. {ai} [{color}{status}{Colors.ENDC}]")
        
    choice = input(f"\nToggle AI (1-{len(available_ais)}) or 'b' to back: ")
    if choice.lower() == 'b':
        return

    try:
        choice_idx = int(choice) - 1
        if 0 <= choice_idx < len(available_ais):
            selected_ai = available_ais[choice_idx]
            
            if selected_ai in current_services:
                current_services.remove(selected_ai)
                print(f"Disabled {selected_ai}")
            else:
                current_services.append(selected_ai)
                print(f"Enabled {selected_ai}")
            
            # Update Redis
            camera_data["services"] = current_services
            # Also update "features" key if present to keep sync
            if "features" in camera_data:
                camera_data["features"] = current_services
                
            r.set(camera_key, json.dumps(camera_data))
            
            # Notify Router via PubSub or assume it polls/L1 cache expiration
            # The router uses an L1 cache with 10s TTL typically, or we can use the API to flush.
            # But direct Redis edit is "God Mode".
            print(f"{Colors.GREEN}Configuration updated!{Colors.ENDC}")
            
        else:
            print("Invalid selection.")
    except ValueError:
        print("Invalid input.")

def main_loop():
    while True:
        cameras = list_cameras()
        if not cameras:
            break
            
        print("\nSelect a camera to manage (Number) or 'q' to quit.")
        choice = input("> ")
        
        if choice.lower() == 'q':
            break
            
        try:
            cam_idx = int(choice) - 1
            if 0 <= cam_idx < len(cameras):
                key, data = cameras[cam_idx]
                toggle_feature(key, data)
            else:
                print("Invalid camera number.")
        except ValueError:
            print("Invalid input.")

if __name__ == "__main__":
    try:
        r.ping()
        main_loop()
    except redis.exceptions.ConnectionError:
        print(f"{Colors.FAIL}Error: Could not connect to Redis at {REDIS_URL}. Is Docker running?{Colors.ENDC}")
