import asyncio
import os
import json
import time
import numpy as np
import cv2
import paddle
import nats
import signal
import threading
import av
from collections import defaultdict
from prometheus_client import start_http_server, Counter, Histogram, Gauge
from aiohttp import web

# CRITICAL: Set Paddle device BEFORE any model loading
paddle.set_device('gpu:0')
print(f"✅ Paddle Device set to: {paddle.get_device()}")

# --- Prometheus Metrics ---
PROCESSING_LATENCY = Histogram('processing_latency_seconds', 'Time spent processing a batch of frames')
FRAMES_PROCESSED = Counter('frames_processed_total', 'Total number of frames processed')

# Start Metrics Server on 8007
try:
    start_http_server(8007)
    print("✅ Prometheus Metrics Server started on port 8007")
except Exception as e:
    print(f"⚠️ Failed to start Prometheus server: {e}")

# Internal Imports
from .config import config
from .database import Database
from .models.pp_human import PPHumanModel
from .models.face import FaceModel
from .models.lpr import LPRModel
from .processors.security import SecurityProcessor
from .loader import load_blacklist
from .cache.face_cache_lfu import FaceCacheLFU


class ThreadedRTSPReader:
    """
    Threaded RTSP reader that continuously decodes frames in background threads.
    Each camera gets its own decoder thread. Frames are stored in a shared buffer.
    """
    
    def __init__(self, camera_urls: dict, target_size=(640, 640)):
        self.camera_urls = camera_urls
        self.target_size = target_size
        self.frames = {}  # cid -> latest frame (resized, RGB)
        self.locks = {}   # cid -> threading.Lock
        self.running = True
        self.threads = []
        
        for cid in camera_urls.keys():
            self.frames[cid] = None
            self.locks[cid] = threading.Lock()
        
        # Start reader threads
        for cid, url in camera_urls.items():
            t = threading.Thread(target=self._reader_loop, args=(cid, url), daemon=True)
            t.start()
            self.threads.append(t)
            print(f"🧵 Started reader thread for camera {cid[:8]}...")
    
    def _letterbox_resize(self, img, target_size):
        """Resize image by stretching to target size (fixes coordinate alignment)."""
        # We use simple resize (stretch) instead of letterbox because
        # SpatialAnalytics polygons are defined relative (0-1) to the FULL frame.
        # If we add black bars (letterbox), the polygons (mapped to full 640x640)
        # will not align with the video content (which is smaller/centered).
        return cv2.resize(img, target_size, interpolation=cv2.INTER_LINEAR)
    
    def _reader_loop(self, cid: str, url: str):
        """Background thread that continuously reads and decodes RTSP frames."""
        while self.running:
            container = None
            try:
                options = {
                    'rtsp_transport': 'tcp',
                    'fflags': 'nobuffer',
                    'flags': 'low_delay',
                    'stimeout': '5000000',
                    'reorder_queue_size': '0'
                }
                container = av.open(url, options=options)
                stream = container.streams.video[0]
                stream.thread_type = 'AUTO'
                
                print(f"✅ Connected: {cid[:8]}...")
                
                for packet in container.demux(stream):
                    if not self.running:
                        break
                    
                    try:
                        frames = packet.decode()
                        if frames:
                            frame_obj = frames[-1]
                            
                            # Convert to RGB numpy (Model expects RGB usually)
                            img = frame_obj.to_ndarray(format='rgb24')
                            
                            # Letterbox resize to target size
                            resized = self._letterbox_resize(img, self.target_size)
                            # Note: resized is now RGB.
                            # cv2 functions usually expect BGR, but we want to feed Model RGB.
                            # We will need to convert to BGR for display/saving if needed.
                            
                            # Update shared buffer
                            with self.locks[cid]:
                                self.frames[cid] = resized
                                
                    except Exception as decode_err:
                        continue
                        
            except Exception as e:
                print(f"❌ Connection Error {cid[:8]}: {e}. Retrying in 5s...")
                time.sleep(5)
            finally:
                if container:
                    try:
                        container.close()
                    except:
                        pass
                
            if self.running:
                time.sleep(1)
    
    def get_frames(self):
        """Get all available frames as a batch."""
        batch_frames = []
        batch_ids = []
        
        for cid in self.camera_urls.keys():
            frame = None
            if self.frames[cid] is not None:
                with self.locks[cid]:
                    frame = self.frames[cid].copy()
            
            if frame is not None:
                batch_frames.append(frame)
                batch_ids.append(cid)
        
        return batch_frames, batch_ids
    
    def stop(self):
        self.running = False


async def run():
    # 1. Initialize Database
    db = Database()
    try:
        db.connect()
    except Exception:
        print("❌ DB Connection Failed")
        return

    # 2. Initialize Models
    try:
        pp_human_model = PPHumanModel()
        pp_human_model.load()
        face_model = FaceModel()
        face_model.load()
        lpr_model = LPRModel()
    except Exception as e:
        print(f"❌ Model Load Failed: {e}")
        return

    # 3. Initialize Security Processor
    face_cache = FaceCacheLFU(l1_capacity=config.FACE_CACHE_L1_CAPACITY)
    processor = SecurityProcessor(
        db=db,
        yolo_model=pp_human_model,
        face_model=face_model,
        lpr_model=lpr_model,
        face_cache=face_cache
    )
    
    # 4. Connect to NATS
    print(f"Connecting to NATS at {config.NATS_URL}...")
    nc = await nats.connect(config.NATS_URL)
    
    # 5. Web Server for Debug Streams
    latest_annotated_frames = {}
    
    async def mjpeg_handler(request):
        camera_id = request.match_info.get('camera_id')
        response = web.StreamResponse(
            status=200, reason='OK',
            headers={'Content-Type': 'multipart/x-mixed-replace;boundary=frame'}
        )
        await response.prepare(request)
        try:
            while True:
                if camera_id in latest_annotated_frames:
                    frame = latest_annotated_frames[camera_id]
                    if frame is not None:
                        ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                        if ret:
                            await response.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                await asyncio.sleep(0.033)  # ~30 FPS
        except:
            pass
        return response

    app = web.Application()
    app.router.add_get('/debug/{camera_id}/mjpeg', mjpeg_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5000)
    await site.start()
    print("✅ Debug Stream Server running on port 5000")

    # 6. Setup RTSP Readers
    rtsp_reader = None
    camera_configs = {}
    
    # Fetch active cameras from DB
    active_cameras = {}
    try:
        with db.conn.cursor() as cur:
            cur.execute("SELECT id, rtsp_url FROM cameras WHERE is_active = true")
            cameras_query = cur.fetchall()
    except Exception as e:
        print(f"❌ Failed to fetch cameras: {e}")
        cameras_query = []
    
    if cameras_query:
        replacements = {
            '{USER}': os.getenv('HIK_USER', ''),
            '{PASS}': os.getenv('HIK_PASS', ''),
            '{IP}': os.getenv('HIK_IP', ''),
            '{PORT_RTSP}': os.getenv('PORT_RTSP', '554')
        }
        
        for row in cameras_query:
            raw_url = row[1]
            # Replace placeholders
            for placeholder, val in replacements.items():
                if val and placeholder in raw_url:
                    raw_url = raw_url.replace(placeholder, val)
            
            # Skip placeholder URLs
            if 'placeholder' in raw_url.lower():
                print(f"⚠️ Skipping placeholder camera: {row[0][:8]}")
                continue
                
            active_cameras[row[0]] = raw_url
    
    if active_cameras:
        print(f"🚀 Starting RTSP readers for {len(active_cameras)} cameras...")
        rtsp_reader = ThreadedRTSPReader(active_cameras, target_size=(640, 640))
        
        # Pre-load camera configurations
        print("🔄 Pre-loading camera configurations...")
        for cam_id in active_cameras.keys():
            try:
                cfg = db.get_camera_config_from_db(cam_id)
                if cfg:
                    camera_configs[cam_id] = cfg
                    print(f"✅ Loaded config for {cam_id[:8]}... (Features: {cfg.get('features')})")
            except Exception as e:
                print(f"❌ Error loading config for {cam_id[:8]}: {e}")
    else:
        print("⚠️ No active cameras found!")

    print("✅ System Started. Entering Main Loop.")
    
    loop = asyncio.get_event_loop()
    
    # --- MAIN LOOP ---
    try:
        frame_cnt = 0
        while True:
            if rtsp_reader is not None:
                try:
                    # Get frames from threaded readers
                    batch_frames, batch_ids = rtsp_reader.get_frames()
                    
                    if not batch_frames:
                        await asyncio.sleep(0.05)
                        continue
                    
                    # Stack into batch array (N, H, W, C)
                    cpu_batch = np.stack(batch_frames, axis=0)
                    
                    # Get configs for each camera
                    batch_configs = [camera_configs.get(cid, {}) for cid in batch_ids]
                    
                    frame_cnt += 1
                    if frame_cnt % 30 == 0:
                        print(f"📦 Processing batch: {len(batch_ids)} cameras, Shape={cpu_batch.shape}, Mean={cpu_batch.mean():.1f}")
                    
                    with PROCESSING_LATENCY.time():
                        # Process the batch
                        processed = processor.process_batch(cpu_batch, batch_ids, batch_configs, gpu_frames=None)
                        
                        # Update debug streams
                        if len(processed) == len(batch_ids):
                            for cid, frame in zip(batch_ids, processed):
                                latest_annotated_frames[cid] = frame
                    
                    FRAMES_PROCESSED.inc(len(batch_ids))
                    
                    # Small sleep to control frame rate (~30 FPS)
                    await asyncio.sleep(0.01)
                    
                except Exception as e:
                    print(f"❌ Error in main loop: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    await asyncio.sleep(0.1)
            else:
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        print("Stopping...")
    finally:
        if rtsp_reader:
            rtsp_reader.stop()
        if runner:
            await runner.cleanup()
        await nc.close()
        db.close()

if __name__ == '__main__':
    try:
        import uvloop
        uvloop.install()
    except:
        pass
    asyncio.run(run())
