import cv2
import os
import time
import av

# Get Env
USER = os.getenv('HIK_USER', 'admin')
PASS = os.getenv('HIK_PASS', '12345')
IP = os.getenv('HIK_IP', '192.168.1.64')
PORT = os.getenv('PORT_RTSP', '554')

# Target URL (from previous step)
RAW_URL = "rtsp://{USER}:{PASS}@{IP}:{PORT_RTSP}/Streaming/Channels/201"
URL = RAW_URL.replace('{USER}', USER).replace('{PASS}', PASS).replace('{IP}', IP).replace('{PORT_RTSP}', PORT)

print(f"🔬 Testing RTSP Stream: {URL}")

# Test 1: OpenCV
print("\n--- Test 1: OpenCV ---")
cap = cv2.VideoCapture(URL)
if not cap.isOpened():
    print("❌ OpenCV failed to open URL.")
else:
    print("✅ OpenCV Opened stream.")
    frames = 0
    t0 = time.time()
    try:
        while time.time() - t0 < 5.0:
            ret, frame = cap.read()
            if not ret:
                print("❌ OpenCV read failed (empty frame).")
                break
            frames += 1
            if frames % 10 == 0:
                print(f"  Captured {frames} frames...")
    except KeyboardInterrupt:
        pass
        
    dur = time.time() - t0
    fps = frames / dur
    print(f"📊 OpenCV Result: {frames} frames in {dur:.2f}s = {fps:.2f} FPS")
    cap.release()

# Test 2: PyAV
print("\n--- Test 2: PyAV (Used by App) ---")
try:
    container = av.open(URL, options={'rtsp_transport': 'tcp', 'stimeout': '5000000'})
    stream = container.streams.video[0]
    print("✅ PyAV Opened stream.")
    
    frames = 0
    t0 = time.time()
    for packet in container.demux(stream):
        if time.time() - t0 > 5.0:
            break
        try:
            for frame in packet.decode():
                frames += 1
                if frames % 10 == 0:
                    print(f"  Decoded {frames} frames...")
        except Exception as e:
            print(f"  Decode error: {e}")
            
    dur = time.time() - t0
    fps = frames / dur
    print(f"📊 PyAV Result: {frames} frames in {dur:.2f}s = {fps:.2f} FPS")
    container.close()
except Exception as e:
    print(f"❌ PyAV Failed: {e}")
