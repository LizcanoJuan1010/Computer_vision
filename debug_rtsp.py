import cv2
import os
import time
import sys

# IP and Creds from env (verified in previous step)
HIK_USER = os.getenv('HIK_USER', 'pruebasia')
HIK_PASS = os.getenv('HIK_PASS', 'pruebas*2026')
HIK_IP = os.getenv('HIK_IP', '186.31.68.234')
PORT_RTSP = os.getenv('PORT_RTSP', '554')

CAMERAS = {
    "101 (New)": f"rtsp://{HIK_USER}:{HIK_PASS}@{HIK_IP}:{PORT_RTSP}/Streaming/Channels/101",
    "102 (Substream)": f"rtsp://{HIK_USER}:{HIK_PASS}@{HIK_IP}:{PORT_RTSP}/Streaming/Channels/102",
    "701 (Cam 7)": f"rtsp://{HIK_USER}:{HIK_PASS}@{HIK_IP}:{PORT_RTSP}/Streaming/Channels/701"
}

def check_stream(name, url):
    print(f"\n📡 Testing {name}...")
    print(f"URL: {url}")
    
    cap = cv2.VideoCapture(url)
    
    if not cap.isOpened():
        print(f"❌ Failed to open stream for {name}")
        # Try to get backend info?
        return
    
    print(f"✅ Stream successfully opened for {name}")
    
    # Try to read 10 frames
    success_count = 0
    start = time.time()
    for i in range(10):
        ret, frame = cap.read()
        if ret:
            success_count += 1
            if i == 0:
                h, w, c = frame.shape
                fps = cap.get(cv2.CAP_PROP_FPS)
                print(f"   ℹ️ Frame 0 properties: {w}x{h}, {c} channels. Reported FPS: {fps}")
                if frame.mean() < 5:
                    print(f"   ⚠️ Frame seems completely black/dark (Mean: {frame.mean():.2f})")
                else:
                    print(f"   ✅ Frame content detected (Mean: {frame.mean():.2f})")
        else:
            print(f"   ⚠️ Failed to read frame {i}")
            
    cap.release()
    
    if success_count > 0:
        duration = time.time() - start
        print(f"✅ Successfully read {success_count}/10 frames in {duration:.2f}s")
        # Estimate: 2560x1440 stream is usually ~4-8 Mbps (H.264).
    else:
        print(f"❌ Opened but failed to read valid frames.")

if __name__ == "__main__":
    print("------------------------------------------------")
    print("🔍 RTSP Diagnostic Tool")
    print("------------------------------------------------")
    try:
        if "ffmpeg" in os.popen("which ffmpeg").read():
             print("ℹ️ ffmpeg is present")
        else:
             print("ℹ️ ffmpeg not found in path")
    except:
        pass
        
    for name, url in CAMERAS.items():
        check_stream(name, url)
