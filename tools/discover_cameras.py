import cv2
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

# Try to load .env manually if not in env
# Try to load .env manually
def load_env():
    # Start from script directory
    current = os.path.dirname(os.path.abspath(__file__))
    # Check up to 3 levels up
    for _ in range(3):
        env_path = os.path.join(current, ".env")
        if os.path.exists(env_path):
            print(f"Loading .env from {env_path}")
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"): continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        if not os.getenv(k):
                            os.environ[k] = v
            return
        current = os.path.dirname(current)

load_env()

USER = os.getenv("HIK_USER", "admin")
PASS = os.getenv("HIK_PASS", "password")
IP = os.getenv("HIK_IP", "192.168.1.64")
PORT = os.getenv("PORT_RTSP", "554")

print(f"Scanning cameras on {IP}:{PORT} as user '{USER}'...")

def check_channel(channel_id):
    url = f"rtsp://{USER}:{PASS}@{IP}:{PORT}/Streaming/Channels/{channel_id}"
    try:
        # We assume 101, 201 etc are main streams
        cap = cv2.VideoCapture(url)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                return channel_id, url
        cap.release()
    except:
        pass
    return None

def scan():
    # Hikvision typically uses 101, 201, 301... up to maybe 6401?
    # Let's scan 101 to 3201
    
    channels_to_check = []
    # Main streams (x01)
    for i in range(1, 33):
        channels_to_check.append(i * 100 + 1)
    # Sub streams (x02) - Optional, user usually wants main
    # for i in range(1, 33):
    #     channels_to_check.append(i * 100 + 2)

    valid_cameras = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_channel, ch): ch for ch in channels_to_check}
        for future in futures:
            result = future.result()
            if result:
                 ch, url = result
                 print(f"[FOUND] Channel {ch}: {url}")
                 valid_cameras.append(url)
            else:
                 # print(f"[...] Checked {futures[future]}")
                 pass

    print("\n=== Valid RTSP URLs ===")
    for c in sorted(valid_cameras):
        print(c)
    
    # Save to file
    with open("available_cameras.txt", "w") as f:
        for c in sorted(valid_cameras):
            f.write(c + "\n")
    print(f"\nSaved list to {os.path.abspath('available_cameras.txt')}")

if __name__ == "__main__":
    scan()
