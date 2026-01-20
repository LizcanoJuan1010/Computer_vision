import asyncio
import os
os.environ["FLAGS_enable_pir_api"] = "0" # CRITICAL: Disable PIR to fixture legacy model crashes
import json
import time
import numpy as np
import cv2
#import paddle
import nats
import signal
import threading
import av
from collections import defaultdict
from prometheus_client import start_http_server, Counter, Histogram, Gauge
from aiohttp import web

# CRITICAL: Set Paddle device BEFORE any model loading
# paddle.set_device('gpu:0') # DISABLED: Conflict with ONNX Runtime on RTX 5060 Ti?
# print(f"✅ Paddle Device set to: {paddle.get_device()}")

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
from .models.pp_vehicle import PPVehicleModel # Added
from .models.face import FaceModel
from .models.lpr_onnx import LPRModelONNX # Changed from .lpr
from .processors.security import SecurityProcessor
from .loader import load_blacklist
from .cache.face_cache_lfu import FaceCacheLFU


class ThreadedRTSPReader:
    """
    Threaded RTSP reader that continuously decodes frames in background threads.
    Each camera gets its own decoder thread. Frames are stored in a shared buffer.
    Supports dynamic adding/removing of cameras.
    """
    
    def __init__(self, camera_urls: dict, target_size=(640, 640)):
        self.camera_urls = {} # Cid -> URL
        self.target_size = target_size
        self.frames = {}           # cid -> latest frame (resized, RGB)
        self.original_frames = {}  # cid -> original frame (RGB)
        self.locks = {}            # cid -> threading.Lock
        self.running = True
        self.threads = {}          # cid -> Thread
        
        # Initial Load
        self.update(camera_urls)
            
    def _letterbox_resize(self, img, target_size):
        """Resize image by stretching to target size (fixes coordinate alignment)."""
        return cv2.resize(img, target_size, interpolation=cv2.INTER_LINEAR)
    
    def add_camera(self, cid, url):
        if cid in self.threads and self.threads[cid].is_alive():
            print(f"⚠️ Camera {cid[:8]} already running.", flush=True)
            return

        print(f"➕ Adding camera {cid[:8]}...", flush=True)
        self.camera_urls[cid] = url
        self.frames[cid] = None
        self.original_frames[cid] = None
        self.locks[cid] = threading.Lock()
        
        t = threading.Thread(target=self._reader_loop, args=(cid, url), daemon=True)
        t.start()
        self.threads[cid] = t
        print(f"🧵 Started reader thread for camera {cid[:8]}...", flush=True)

    def remove_camera(self, cid):
        if cid in self.camera_urls:
            print(f"➖ Removing camera {cid[:8]}...", flush=True)
            del self.camera_urls[cid] # This signals the thread to stop
            # We cleanup frames/locks in the get_frames loop or let them stay until garbage collected?
            # Better to clean up to save memory
            if cid in self.frames: del self.frames[cid]
            if cid in self.original_frames: del self.original_frames[cid]
            if cid in self.locks: del self.locks[cid]
            if cid in self.threads: del self.threads[cid]

    def update(self, new_camera_urls: dict):
        """Update the list of active cameras. Valid for Hot-Reload."""
        current_cids = set(self.camera_urls.keys())
        new_cids = set(new_camera_urls.keys())
        
        # Calculate diff
        to_add = new_cids - current_cids
        to_remove = current_cids - new_cids
        
        if not to_add and not to_remove:
            return

        print(f"🔄 Updating Cameras. Adding: {len(to_add)}, Removing: {len(to_remove)}", flush=True)

        for cid in to_remove:
            self.remove_camera(cid)
            
        for cid in to_add:
            self.add_camera(cid, new_camera_urls[cid])

    def _reader_loop(self, cid: str, url: str):
        """Background thread that continuously reads and decodes RTSP frames."""
        print(f"🎬 Stream Thread Started: {cid[:8]}", flush=True)
        while self.running and cid in self.camera_urls:
            container = None
            try:
                options = {
                    'rtsp_transport': 'tcp',
                    'stimeout': '5000000',
                    # 'fflags': 'nobuffer', # Possible culprit
                    # 'flags': 'low_delay',
                    # 'reorder_queue_size': '0'
                }
                container = av.open(url, options=options)
                stream = container.streams.video[0]
                stream.thread_type = 'AUTO'
                
                print(f"✅ Connected: {cid[:8]}...", flush=True)
                
                packet_count = 0
                for packet in container.demux(stream):
                    if not self.running or cid not in self.camera_urls:
                        print(f"🛑 Stopping stream {cid[:8]} (Signal received)", flush=True)
                        break
                    
                    try:
                        frames = packet.decode()
                        if frames:
                            packet_count += 1
                            if packet_count % 100 == 0:
                                print(f"📺 {cid[:8]} Decoded {packet_count} frames...", flush=True)
                            
                            frame_obj = frames[-1]
                            
                            # Convert to RGB numpy (Model expects RGB usually)
                            img = frame_obj.to_ndarray(format='rgb24')
                            
                            # Performance check
                            h, w = img.shape[:2]
                            if w > 1280:
                                new_w = 1280
                                new_h = int(h * (1280 / w))
                                img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                            
                            resized = self._letterbox_resize(img, self.target_size)
                            
                            # Update shared buffer (store both)
                            if cid in self.locks: # Check if still valid
                                with self.locks[cid]:
                                    self.frames[cid] = resized
                                    self.original_frames[cid] = img
                                
                    except Exception as decode_err:
                        # print(f"⚠️ Decode Error: {decode_err}", flush=True)
                        continue
                        
            except Exception as e:
                # Only log if still intended to run
                if self.running and cid in self.camera_urls:
                    print(f"❌ Connection Error {cid[:8]}: {e}. Retrying in 5s...", flush=True)
                    time.sleep(5)
            finally:
                if container:
                    try:
                        container.close()
                    except:
                        pass
                
            if self.running and cid in self.camera_urls:
                time.sleep(1)
        print(f"👋 Stream Thread Exited: {cid[:8]}", flush=True)
    
    def get_frames(self):
        """Get all available frames as a batch.
        Returns: (resized_frames, original_frames, camera_ids)
        """
        batch_frames = []
        batch_originals = []
        batch_ids = []
        
        # Iterate over a copy of keys to avoid runtime error if dict changes size
        for cid in list(self.camera_urls.keys()):
            frame = None
            original = None
            
            # Safe access
            try:
                if cid in self.frames and self.frames[cid] is not None:
                    with self.locks[cid]:
                        frame = self.frames[cid].copy()
                        original = self.original_frames[cid].copy() if self.original_frames[cid] is not None else None
                
                if frame is not None and original is not None:
                    batch_frames.append(frame)
                    batch_originals.append(original)
                    batch_ids.append(cid)
            except KeyError:
                continue # Camera might have been removed mid-loop
        
        return batch_frames, batch_originals, batch_ids
    
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


    try:
        # 3. LPR Model (ONNX - Stable)
        print("DEBUG: Loading LPR Model (ONNX)...")
        lpr_model = LPRModelONNX()
        lpr_model.load()
        print("DEBUG: LPR Model Loaded.")
        # lpr_model = None

        print("DEBUG: Loading PP-Human Model...")
        pp_human_model = PPHumanModel()
        pp_human_model.load()
        print("DEBUG: PP-Human Model Loaded.")
        
        print("DEBUG: Loading Face Model...")
        face_model = FaceModel()
        print("DEBUG: FaceModel Instantiated.")
        face_model.load()
        print("DEBUG: Face Model Loaded.")
        
        # 3.5 Vehicle Model (Unified with PP-Human)
        # We use the same RT-DETR session for both humans and vehicles
        # to save VRAM and avoid conflicting GPU contexts.
        vehicle_model = None # Handled inside SecurityProcessor using yolo_model results

    except Exception as e:
        print(f"❌ Model Load Failed: {e}")
        return

    # 4. Security Processor (Orchestrator)
    print("Initializing Security Processor...")
    face_cache = FaceCacheLFU(l1_capacity=config.FACE_CACHE_L1_CAPACITY)
    loop = asyncio.get_event_loop() # Get the event loop here
    processor = SecurityProcessor(
        db=db, 
        yolo_model=pp_human_model, 
        face_model=face_model, 
        vehicle_model=vehicle_model,  # PP-Vehicle enabled for full LPR pipeline
        lpr_model=lpr_model,  # ONNX LPR model
        face_cache=face_cache,
        loop=loop
    )
    # Note: pp_human_model is passed as 'yolo_model' arg
    
    # 5. Connect to NATS
    print(f"Connecting to NATS at {config.NATS_URL}...")
    nc = await nats.connect(config.NATS_URL)
    
    # 6. Web Server for Debug Streams
    latest_annotated_frames = {}
    
    async def mjpeg_handler(request):
        camera_id = request.match_info.get('camera_id')
        print(f"📹 MJPEG Request for camera: {camera_id}", flush=True)
        print(f"📹 Available frames: {list(latest_annotated_frames.keys())}", flush=True)
        
        response = web.StreamResponse(
            status=200, reason='OK',
            headers={'Content-Type': 'multipart/x-mixed-replace;boundary=frame'}
        )
        await response.prepare(request)
        frame_count = 0
        try:
            while True:
                if camera_id in latest_annotated_frames:
                    frame = latest_annotated_frames[camera_id]
                    if frame is not None:
                        frame_count += 1
                        if frame_count == 1:
                            print(f"📹 First frame found for {camera_id}, shape: {frame.shape}", flush=True)
                        # Convert RGB back to BGR for OpenCV encoding
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        ret, buffer = cv2.imencode('.jpg', frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                        if ret:
                            await response.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                await asyncio.sleep(0.033)  # ~30 FPS
        except Exception as e:
            print(f"❌ MJPEG Error: {e}", flush=True)
        return response

    app = web.Application()
    app.router.add_get('/debug/{camera_id}/mjpeg', mjpeg_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5005)
    await site.start()
    print("✅ Debug Stream Server running on port 5005")

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
            # Sharding Logic: Filter cameras for this instance
            if config.TOTAL_INSTANCES > 1:
                try:
                    # Deterministic mapping (UUID Hex -> Int -> Modulo)
                    cam_int_val = int(row[0].replace('-', ''), 16)
                    if cam_int_val % config.TOTAL_INSTANCES != config.INSTANCE_ID:
                        continue
                except Exception as e:
                    print(f"⚠️ Sharding Error for {row[0]}: {e}. Processing anyway.")

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
        target_h = int(os.getenv('RESIZE_HEIGHT', 360))
        target_w = int(os.getenv('RESIZE_WIDTH', 640))
        print(f"📏 Target Resolution: {target_w}x{target_h}")
        rtsp_reader = ThreadedRTSPReader(active_cameras, target_size=(target_w, target_h))
        
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
    last_camera_update = time.time()
    
    try:
        frame_cnt = 0
        while True:
            # --- Dynamic Camera Update (Hot Reload) ---
            if time.time() - last_camera_update > 10:
                last_camera_update = time.time()
                try:
                    # Run DB fetch in executor to avoid blocking loop
                    def _fetch_cams():
                        with db.conn.cursor() as cur:
                            cur.execute("SELECT id, rtsp_url FROM cameras WHERE is_active = true")
                            return cur.fetchall()
                    
                    rows = await loop.run_in_executor(None, _fetch_cams)
                    
                    new_active_cameras = {}
                    replacements = {
                        '{USER}': os.getenv('HIK_USER', ''),
                        '{PASS}': os.getenv('HIK_PASS', ''),
                        '{IP}': os.getenv('HIK_IP', ''),
                        '{PORT_RTSP}': os.getenv('PORT_RTSP', '554')
                    }
                    
                    for row in rows:
                        # Sharding Logic
                        if config.TOTAL_INSTANCES > 1:
                            try:
                                cam_int_val = int(row[0].replace('-', ''), 16)
                                if cam_int_val % config.TOTAL_INSTANCES != config.INSTANCE_ID:
                                    continue
                            except: pass
                            
                        raw_url = row[1]
                        for placeholder, val in replacements.items():
                            if val and placeholder in raw_url:
                                raw_url = raw_url.replace(placeholder, val)
                        
                        if 'placeholder' in raw_url.lower(): continue
                        new_active_cameras[row[0]] = raw_url
                    
                    # Update Reader
                    if rtsp_reader:
                        rtsp_reader.update(new_active_cameras)
                    
                    # Update Configs for new cameras
                    for cid in new_active_cameras.keys():
                        if cid not in camera_configs:
                            try:
                                cfg = await loop.run_in_executor(None, lambda: db.get_camera_config_from_db(cid))
                                if cfg:
                                    camera_configs[cid] = cfg
                                    print(f"✅ Loaded NEW config for {cid[:8]}...", flush=True)
                            except Exception as e:
                                print(f"❌ Config load error: {e}", flush=True)

                except Exception as e:
                    print(f"⚠️ Hot Reload Error: {e}", flush=True)

            if rtsp_reader is not None:
                try:
                    # Get frames from threaded readers
                    # 2. Grab latest frames
                    batch_frames, batch_originals, batch_ids = rtsp_reader.get_frames()
                    
                    if frame_cnt % 20 == 0:
                         print(f"📦 Heartbeat: Loop active. Batch size: {len(batch_frames)}", flush=True)

                    if not batch_frames:
                        if frame_cnt % 50 == 0:
                             print("💤 Idle (No frames from any camera)", flush=True)
                        time.sleep(0.01)
                        continue
                        
                    if frame_cnt % 10 == 0:
                         print(f"📦 Processing batch of {len(batch_frames)} frames", flush=True)
                    
                    # Keep frames as lists (different resolutions)
                    # cpu_batch = np.stack(batch_frames, axis=0) - Not needed
                    original_batch = batch_originals  # List of originals for model
                    
                    # Get configs for each camera
                    batch_configs = [camera_configs.get(cid, {}) for cid in batch_ids]
                    
                    # DEBUG: Print features for first cam
                    if batch_configs and frame_cnt % 50 == 0:
                        print(f"⚙️ Features for {batch_ids[0][:8]}: {batch_configs[0].get('features', [])}", flush=True)
                    
                    frame_cnt += 1
                    
                    with PROCESSING_LATENCY.time():
                        t0 = time.time()
                        
                        # Process batch in Executor to avoid blocking AsyncIO Loop (Heartbeats, Web Server)
                        # We use a ThreadPoolExecutor (logic within security.py is CPU bound mostly but calls GPU)
                        # Since Python GIL exists, this helps mostly if there are IO bound tasks inside or if using released GIL libs (like OpenCV/Paddle/Numpy often do).
                        processed = await loop.run_in_executor(
                            None, 
                            lambda: processor.process_batch(original_batch, batch_ids, batch_configs, gpu_frames=None)
                        )
                        
                        t1 = time.time()
                        
                        latency_ms = (t1 - t0) * 1000
                        if frame_cnt % 10 == 0:
                            print(f"📦 Batch: {len(batch_ids)} cams | Latency: {latency_ms:.1f}ms | FPS: {1000/latency_ms if latency_ms > 0 else 0:.1f}", flush=True)

                        # Update debug streams
                        processed_frames, batch_meta = processed if processed else ([], [])
                        if processed_frames and len(processed_frames) == len(batch_ids):
                            for cid, frame in zip(batch_ids, processed_frames):
                                latest_annotated_frames[cid] = frame
                        
                        # ✅ PUBLISH METADATA TO NATS
                        if batch_meta and len(batch_meta) == len(batch_ids):
                            print(f"📢 Publishing batch of {len(batch_meta)} items", flush=True)
                            for cid, meta in zip(batch_ids, batch_meta):
                                # DEBUG ATTRIBUTES
                                if "persons" in meta and meta["persons"]:
                                    for p in meta["persons"]:
                                        if "attributes" in p and p["attributes"]:
                                            print(f"👤 Person Attr: {p['attributes']}", flush=True)
                                if "vehicles" in meta and meta["vehicles"]:
                                    for v in meta["vehicles"]:
                                        if "attributes" in v and v["attributes"]:
                                            print(f"🚗 Vehicle Attr: {v['attributes']}", flush=True)
                                
                                try:
                                    subject = f"camera.debug.{cid}"
                                    # print(f"📤 Publishing to {subject}", flush=True)
                                    payload = json.dumps(meta).encode()
                                    if frame_cnt % 50 == 0:
                                        print(f"🐛 DEBUG META PAYLOAD ({cid[:8]}): {json.dumps(meta)[:200]}...", flush=True)
                                    await nc.publish(subject, payload)
                                except Exception as e:
                                    print(f"⚠️ NATS Publish Error: {e}", flush=True)
                        else:
                             print(f"⚠️ Batch Mismatch: IDs={len(batch_ids)} Meta={len(batch_meta) if batch_meta else 'None'}", flush=True)
                    
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
    try:
        asyncio.run(run())
    except Exception as e:
        import traceback
        with open("/app/crash.log", "w") as f:
            f.write(f"CRITICAL CRASH: {e}\n")
            traceback.print_exc(file=f)
        print("❌ CRITICAL FAILURE WRITTEN TO /app/crash.log")
        time.sleep(10) # Wait to allow log capture
