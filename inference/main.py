import asyncio
import os
import json
import time
import numpy as np
import cv2  # Utility only
import paddle
import nats
import signal
from collections import defaultdict
from prometheus_client import start_http_server, Counter, Histogram, Gauge
from aiohttp import web

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

# DALI Pipeline Imports
try:
    from .pipeline.dali import RTSPSource, rtsp_pipeline, HAS_DALI
    from nvidia.dali.plugin.paddle import DALIGenericIterator
    from nvidia.dali.plugin.base_iterator import LastBatchPolicy
except ImportError:
    print("⚠️ DALI Import Error. DALI will be disabled.")
    HAS_DALI = False
    RTSPSource = None
    rtsp_pipeline = None

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
        lpr_model.load()
        load_blacklist(face_model) # Legacy
    except Exception as e:
        print(f"❌ Error loading models: {e}")
        return

    # 2.5 Initialize Face Cache
    face_cache = None
    if config.FACE_CACHE_ENABLED:
        try:
            print("🔄 Initializing FaceCacheLFU...")
            face_cache = FaceCacheLFU(
                l1_capacity=config.FACE_CACHE_L1_CAPACITY,
                redis_url=config.FACE_CACHE_REDIS_URL,
                default_threshold=config.SIMILARITY_THRESHOLD
            )
            await face_cache.initialize()
            await face_cache.load_global_blacklist(db)
            print(f"✅ FaceCacheLFU initialized.")
        except Exception as e:
            print(f"⚠️ Face cache init failed: {e}")
            face_cache = None

    # 3. Initialize Processor
    loop = asyncio.get_running_loop()

    def publish_alarm(subject, data):
        if 'nc' in locals() and nc and nc.is_connected:
            payload = json.dumps(data).encode()
            loop.call_soon_threadsafe(lambda: asyncio.create_task(nc.publish(subject, payload)))

    processor = SecurityProcessor(db, pp_human_model, face_model, lpr_model, face_cache=face_cache, publish_callback=publish_alarm, loop=loop)

    # 4. Connect to NATS
    print(f"Connecting to NATS at {config.NATS_URL}...")
    nc = await nats.connect(config.NATS_URL)
    
    
    # --- Web Server (Debug) ---
    # Start BEFORE DALI init to ensure port is open even if RTSP connects slowly
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
                    ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    if ret:
                        await response.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                await asyncio.sleep(0.04) # ~250 FPS cap check
        except: pass
        return response

    app = web.Application()
    app.router.add_get('/debug/{camera_id}/mjpeg', mjpeg_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5000)
    await site.start()
    print("✅ Debug Stream Server running on port 5000")

    # 5. DALI / RTSP Setup
    rtsp_source = None
    dali_iter = None
    
    if HAS_DALI:
         BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1"))
         
         # Fetch Active RTSP Cameras
         active_cameras = {} 
         cursor = db.conn.cursor()
         cursor.execute("SELECT id, rtsp_url, meta_info FROM cameras WHERE is_active = true AND rtsp_url IS NOT NULL")
         rows = cursor.fetchall()
         
         for row in rows:
             if row[1] and row[1].startswith('rtsp'):
                raw_url = row[1]
                # Replace placeholders with env vars
                replacements = {
                    "{USER}": os.getenv("HIK_USER", "admin"),
                    "{PASS}": os.getenv("HIK_PASS", "password"),
                    "{IP}": os.getenv("HIK_IP", "127.0.0.1"),
                    "{PORT_RTSP}": os.getenv("PORT_RTSP", "554")
                }
                for placeholder, val in replacements.items():
                    if val and placeholder in raw_url:
                        raw_url = raw_url.replace(placeholder, val)
                        
                active_cameras[row[0]] = raw_url
                
         if active_cameras:
             print(f"🚀 Initializing DALI Pipeline for {len(active_cameras)} cameras...")
             rtsp_source = RTSPSource(active_cameras, BATCH_SIZE)
             pipe = rtsp_pipeline(source_callback=rtsp_source, batch_size=BATCH_SIZE, num_threads=2, device_id=0)
             pipe.build()
             dali_iter = DALIGenericIterator(pipelines=[pipe], output_map=['frames'], size=-1, auto_reset=True, last_batch_policy=LastBatchPolicy.PARTIAL)
         else:
             print("⚠️ No active RTSP cameras found for DALI.")
    
    # --- Web Server (Debug) ---


    # Load Camera Configurations (Sync at startup)
    camera_configs = {}
    if HAS_DALI and active_cameras:
        print("🔄 Pre-loading camera configurations...")
        for cam_id in active_cameras.keys():
            try:
                cfg = db.get_camera_config_from_db(cam_id)
                if cfg:
                    camera_configs[cam_id] = cfg
                    print(f"✅ Loaded config for {cam_id} (Features: {cfg.get('features')})")
                else:
                    print(f"⚠️ No config found for {cam_id}, using defaults.")
            except Exception as e:
                print(f"❌ Error loading config for {cam_id}: {e}")

    print("✅ System Started. Entering Main Loop.")
    
    # --- MAIN LOOP ---
    try:
        while True:
            # 1. DALI Inference Branch
            print(f"🔄 Loop Tick. DALI? {dali_iter is not None}", flush=True)
            if dali_iter is not None:
                try:
                    # Non-blocking check? DALIGenericIterator is blocking generally but fast on GPU.
                    # We run it in executor if needed, but let's try direct call for raw speed.
                    # Warning: This blocks the asyncio loop!
                    # Ideally: await loop.run_in_executor(None, next, dali_iter)
                    
                    try:
                        def fetch_next():
                            try:
                                return next(dali_iter)
                            except StopIteration:
                                return None
                        data = await loop.run_in_executor(None, fetch_next)
                    except Exception as e:
                        print(f"❌ DALI Fetch Error: {e}", flush=True)
                        data = None

                    if data is None:
                        print("⚠️ End of stream/batch. Resetting.", flush=True)
                        dali_iter.reset()
                        continue
                    
                    # data is list of dicts.
                    tensor_raw = data[0]['frames'] # Paddle Raw Tensor (GPU)
                    # Wrap in high-level Tensor to get .numpy()
                    tensor_batch = paddle.to_tensor(tensor_raw).numpy() # Convert to CPU Numpy

                    # Update IDs
                    batch_ids = rtsp_source.current_batch_ids
                    # batch_configs = [{}] * len(batch_ids) # TODO: fetching config
                    batch_configs = [camera_configs.get(cid, {}) for cid in batch_ids]
                    
                    with PROCESSING_LATENCY.time():
                         # Pass CPU Numpy batch to processor
                         processed = processor.process_batch(tensor_batch, batch_ids, batch_configs)
                         
                         # Update Debug Streams
                         # Processed returns list of numpy/cpu frames (annotated)
                         # We need to map them back to IDs
                         if len(processed) == len(batch_ids):
                             for cid, frame in zip(batch_ids, processed):
                                 latest_annotated_frames[cid] = frame
                                 
                    FRAMES_PROCESSED.inc(len(batch_ids))
                    
                    # Debug: Check what indices we actually have
                    if len(latest_annotated_frames) > 0: # Print every batch for now
                        keys = list(latest_annotated_frames.keys())
                        print(f"🔍 DEBUG: Active Video Keys: {keys}")
                        # Check first frame content
                        if keys:
                             sample_frame = latest_annotated_frames[keys[0]]
                             if sample_frame is not None:
                                 print(f"🔍 DEBUG: Frame Stats - Shape: {sample_frame.shape}, Mean: {sample_frame.mean()}")
                             else:
                                 print("🔍 DEBUG: Frame is None!")
                    
                except StopIteration:
                    print("⚠️ StopIteration caught! Resetting DALI.", flush=True)
                    dali_iter.reset()
                except Exception as e:
                    print(f"❌ Error in DALI loop: {e}", flush=True)
                    await asyncio.sleep(0.1) # Backoff
            else:
                # No DALI? Sleep to prevent CPU spin
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        print("Stopping...")
    finally:
        if runner: await runner.cleanup()
        await nc.close()
        db.close()

if __name__ == '__main__':
    try:
        import uvloop
        uvloop.install()
    except: pass
    asyncio.run(run())
