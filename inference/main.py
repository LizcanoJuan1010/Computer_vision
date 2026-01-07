import asyncio
import os
import json
import time
import numpy as np
import cv2
import nats
import signal
from collections import defaultdict
from prometheus_client import start_http_server, Counter, Histogram, Gauge

# --- Prometheus Metrics ---
PROCESSING_LATENCY = Histogram('processing_latency_seconds', 'Time spent processing a batch of frames')
FRAMES_PROCESSED = Counter('frames_processed_total', 'Total number of frames processed')
ACTIVE_ZONES = Gauge('active_zones', 'Number of cameras with active zones', ['type'])

# Start Metrics Server on 8007 (Separate Thread)
try:
    start_http_server(8007)
    print("✅ Prometheus Metrics Server started on port 8007")
except Exception as e:
    print(f"⚠️ Failed to start Prometheus server: {e}")

from .config import config
from .database import Database
from .models.pp_human import PPHumanModel
from .models.face import FaceModel
from .models.lpr import LPRModel
from .processors.security import SecurityProcessor
from .loader import load_blacklist
from .cache.face_cache_lfu import FaceCacheLFU

async def run():
    # 1. Initialize Database
    db = Database()
    try:
        db.connect()
    except Exception:
        return

    # 2. Initialize Models
    try:
        # PPHumanModel handles Detection, Tracking, and Action (Fight/Fall)
        pp_human_model = PPHumanModel()
        pp_human_model.load()

        face_model = FaceModel()
        face_model.load()
        
        lpr_model = LPRModel()
        lpr_model.load()

        # Load Blacklist (legacy - will be replaced by cache)
        load_blacklist(face_model)

    except Exception as e:
        print(f"Error loading models: {e}")
        return

    # 2.5 Initialize Face Cache (LFU Hybrid)
    face_cache = None
    if config.FACE_CACHE_ENABLED:
        try:
            print("🔄 Initializing FaceCacheLFU (Hybrid L1+L2)...")
            face_cache = FaceCacheLFU(
                l1_capacity=config.FACE_CACHE_L1_CAPACITY,
                redis_url=config.FACE_CACHE_REDIS_URL,
                default_threshold=config.SIMILARITY_THRESHOLD
            )
            await face_cache.initialize()

            # Load global blacklist into L1 (always available)
            await face_cache.load_global_blacklist(db)

            print(f"✅ FaceCacheLFU initialized (L1 capacity: {config.FACE_CACHE_L1_CAPACITY})")
        except Exception as e:
            print(f"⚠️  Failed to initialize face cache: {e}")
            print("⚠️  Falling back to database search")
            try:
                db.conn.rollback()
            except:
                pass
            face_cache = None

    # 3. Initialize Processor
    # Thread-safe publisher
    loop = asyncio.get_running_loop()

    def publish_alarm(subject, data):
        # Schedule nats publish on the main loop
        if 'nc' in locals() and nc and nc.is_connected:
            import json
            payload = json.dumps(data).encode()
            loop.call_soon_threadsafe(lambda: asyncio.create_task(nc.publish(subject, payload)))

    processor = SecurityProcessor(db, pp_human_model, face_model, lpr_model, face_cache=face_cache, publish_callback=publish_alarm)

    # 4. Connect to NATS
    print(f"Connecting to NATS at {config.NATS_URL}...")
    try:
        nc = await nats.connect(config.NATS_URL)
    except Exception as e:
        print(f"Error connecting to NATS: {e}")
        return
    
    print(f"Subscribing to {config.SUBJECT}...")

    # Connect to Redis for Config
    import redis.asyncio as redis
    import json
    import os
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6380/0")
    redis_client = redis.from_url(redis_url, decode_responses=True)
    
    # Simple L1 Cache for Config
    config_cache = {}
    last_config_update = {}

    async def get_camera_config(cam_id, org_slug=None, zone_slug=None):
        import time
        now = time.time()

        # Build cache key (multi-tenancy aware)
        cache_key = f"{org_slug}:{zone_slug}:{cam_id}" if org_slug and zone_slug else cam_id

        # Refresh every 5 seconds
        if cache_key in config_cache and (now - last_config_update.get(cache_key, 0)) < 5:
            return config_cache[cache_key]

        try:
            # Try Redis with fallback: org-based key first, then simple key
            redis_keys = [
                f"config:org:{org_slug}:zone:{zone_slug}:camera:{cam_id}" if org_slug and zone_slug else None,
                f"config:camera:{cam_id}"
            ]
            redis_keys = [k for k in redis_keys if k]  # Remove None

            data = None
            for redis_key in redis_keys:
                data = await redis_client.get(redis_key)
                if data:
                    cfg = json.loads(data)
                    config_cache[cache_key] = cfg
                    last_config_update[cache_key] = now
                    return cfg
        except Exception:
            pass

        # Fallback: Query Postgres directly (Synchronous but necessary on cold start)
        # We run in thread to avoid blocking loop
        try:
             cfg = await asyncio.to_thread(db.get_camera_config_from_db, cam_id)
             if cfg:
                 # Update L1 cache
                 config_cache[cache_key] = cfg
                 last_config_update[cache_key] = now
                 
                 # Optional: Populate L2 Redis (Write-Through)
                 if org_slug and zone_slug:
                      # We don't have org_slug/zone_slug if called with just cam_id
                      pass 
                 return cfg
        except Exception as e:
             print(f"DB Config Fallback Error: {e}")

        return None

    # Queue for frames
    # Reduced to 30 to avoid "ghosting" but allow fluidity
    frame_queue = asyncio.Queue(maxsize=30)

    async def batch_processor():
        print("Batch processor started.")
        batch_size = 4 # Configurable
        batch_timeout = 0.005 # 5ms (Reduced for lower latency)
        
        while True:
            raw_items = []
            
            # 1. Collect Batch of Raw Items
            try:
                # Wait for first item
                item = await frame_queue.get()
                raw_items.append(item)
                
                # Try to fill batch without waiting too long
                start_wait = asyncio.get_event_loop().time()
                while len(raw_items) < batch_size:
                    timeout = batch_timeout - (asyncio.get_event_loop().time() - start_wait)
                    if timeout <= 0:
                        break
                    
                    try:
                        item = await asyncio.wait_for(frame_queue.get(), timeout=timeout)
                        raw_items.append(item)
                    except asyncio.TimeoutError:
                        break
                
                # 2. Decode and Process Batch
                if raw_items:
                    try:
                        # Decode in thread pool (CPU bound)
                        def decode_and_process(items):
                            frames = []
                            valid_camera_ids = []
                            valid_configs = []
                            
                            for it in items:
                                np_arr = np.frombuffer(it['data'], np.uint8)
                                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                                if frame is not None:
                                    # Convert BGR (OpenCV) to RGB (Paddle)
                                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                    frames.append(frame)
                                    valid_camera_ids.append(it['camera_id'])
                                    valid_configs.append(it['config'])
                            
                            if frames:
                                with PROCESSING_LATENCY.time():
                                     processed = processor.process_batch(frames, valid_camera_ids, valid_configs)
                                
                                # Metrics Update
                                FRAMES_PROCESSED.inc(len(frames))
                                
                                # START FIX: Return pairs of (id, frame) to ensure correct mapping
                                return list(zip(valid_camera_ids, processed))
                            return []

                        # Returns list of (camera_id, processed_frame)
                        processed_results = await asyncio.to_thread(decode_and_process, raw_items)
                        
                        # Update global cache for streaming
                        if processed_results:
                             for cam_id, frame in processed_results:
                                 latest_annotated_frames[cam_id] = frame
                    except Exception as e:
                        print(f"Batch processing error: {e}")
                    
                    # Mark tasks as done
                    for _ in range(len(raw_items)):
                        frame_queue.task_done()
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Processor error: {e}")

    # Start Processor Task
    processor_task = asyncio.create_task(batch_processor())

    async def message_handler(msg):
        # Extract Metadata (Multi-Tenancy Aware)
        subject = msg.subject
        camera_id = "unknown"
        org_slug = None
        zone_slug = None

        # Extract from headers (preferred)
        if msg.header:
            camera_id = msg.header.get("camera_id", camera_id)
            org_slug = msg.header.get("org_slug")
            zone_slug = msg.header.get("zone_slug")

        # Fallback: Parse from subject if headers not available
        if camera_id == "unknown":
            parts = subject.split('.')
            if parts[0] == "org" and len(parts) >= 7:
                # New format: org.{org}.zone.{zone}.camera.{id}.frame
                org_slug = parts[1]
                zone_slug = parts[3]
                camera_id = parts[5]
            elif parts[0] == "camera" and len(parts) > 1:
                # Legacy format: camera.{id}.frame
                camera_id = parts[1]

        if camera_id == "unknown":
            camera_id = "cam_01"

        # Fetch Config (prefer header from ingest, fallback to Redis/DB)
        cam_config = None
        if msg.header and "Config" in msg.header:
            try:
                cam_config = json.loads(msg.header["Config"])
                
                # FIX: Handle 'original_features' (from Ingest meta_info) vs 'features'
                features = cam_config.get("features", [])
                if not features and "original_features" in cam_config:
                     features = cam_config["original_features"]
                     cam_config["features"] = features # Normalize
                
                # Check meta_info wrapper
                if not features and "meta_info" in cam_config:
                     meta = cam_config["meta_info"]
                     if "original_features" in meta:
                         features = meta["original_features"]
                         cam_config["features"] = features

                if not features:
                     cam_config = None
            except Exception as e:
                print(f"Error parsing Config header: {e}")

        if not cam_config:
            # print(f"DEBUG [{camera_id}] Fetching config from DB...")
            cam_config = await get_camera_config(camera_id, org_slug, zone_slug)
            if cam_config:
                 pass
                 # print(f"DEBUG [{camera_id}] Loaded Config from DB: {cam_config.get('features')}")
            else:
                 print(f"DEBUG [{camera_id}] DB returned None!", flush=True)

        # Ensure org_id is in config for face cache
        if cam_config and org_slug:
            # Try to get org_id from database based on org_slug
            if 'org_id' not in cam_config:
                # TODO: Query database to get org_id from org_slug
                # For now, use org_slug as org_id (will be UUID in production)
                cam_config['org_id'] = org_slug

        # Push Raw Data to Queue (Drop Oldest Strategy)
        if frame_queue.full():
            try:
                frame_queue.get_nowait() # Discard oldest frame to make space
            except asyncio.QueueEmpty:
                pass

        try:
            frame_queue.put_nowait({
                'data': msg.data, # Raw bytes
                'camera_id': camera_id,
                'config': cam_config
            })
        except asyncio.QueueFull:
            pass # Should not happen with logic above

    async def command_handler(msg):
        subject = msg.subject
        reply = msg.reply
        data = msg.data.decode()
        
        if "register_face" in subject:
             import json
             import base64
             try:
                 payload = json.loads(data)
                 name = payload.get("name")
                 img_b64 = payload.get("image")
                 organization_id = payload.get("organization_id")
                 category = payload.get("category", "KNOWN")
                 meta_info = payload.get("meta_info", {})
                 
                 # Decode Image
                 img_bytes = base64.b64decode(img_b64)
                 np_arr = np.frombuffer(img_bytes, np.uint8)
                 img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                 
                 if img is None:
                     raise ValueError("Invalid image data")
                 
                 print(f"✅ Image decoded: {img.shape}")
                     
                 # Run Face Model
                 faces = face_model.predict(img)
                 print(f"🔍 Face model found {len(faces)} faces")
                 print(f"🔍 Face model found {len(faces)} faces")
                 
                 if not faces:
                      # TRY RGB CONVERSION
                      print("⚠️ No faces in BGR, trying RGB...")
                      img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                      faces = face_model.predict(img_rgb)
                      print(f"🔍 Face model found {len(faces)} faces (RGB)")

                 if not faces:
                      print("⚠️ No face detected. Using DUMMY embedding to allow registration.")
                      embedding = [0.0] * 512
                      # name = name + " (No Face Detected)" # Optional: append to name
                 else:
                      # Get largest
                      face = sorted(faces, key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]))[-1]
                      embedding = face.embedding.tolist()
                 
                 # Save to DB
                 db.cur.execute("""
                    INSERT INTO faces (name, embedding, organization_id, category, meta_info) 
                    VALUES (%s, %s, %s, %s, %s) 
                    RETURNING id
                 """, (name, embedding, organization_id, category, json.dumps(meta_info)))
                 
                 new_id = db.cur.fetchone()[0]
                 db.conn.commit()
                 
                 # Reload In-Memory
                 db.load_faces()
                 
                 response = {"status": "success", "face_id": new_id, "message": f"Did register {name}"}
                 
             except Exception as e:
                 print(f"Register Face Error: {e}")
                 db.conn.rollback()
                 response = {"status": "error", "message": str(e)}
                 
             if reply:
                 await nc.publish(reply, json.dumps(response).encode())

    async def cache_event_handler(msg):
        """
        Handle cache invalidation events from Router API.
        Events: face.registered, face.updated, face.deleted, face.shared_to_global
        """
        subject = msg.subject
        data_str = msg.data.decode()

        if not face_cache:
            return  # Cache not enabled

        try:
            import json
            payload = json.loads(data_str)

            if "face.registered" in subject or "face.updated" in subject:
                # Invalidate specific face in cache
                face_id = payload.get("face_id")
                org_id = payload.get("org_id")

                if face_id and org_id:
                    await face_cache.invalidate(face_id, org_id)
                    print(f"✅ Cache invalidated: face {face_id} in org {org_id}")

            elif "face.deleted" in subject:
                # Invalidate deleted face
                face_id = payload.get("face_id")
                org_id = payload.get("org_id")

                if face_id and org_id:
                    await face_cache.invalidate(face_id, org_id)
                    print(f"✅ Cache invalidated (deleted): face {face_id}")

            elif "face.shared_to_global" in subject:
                # Reload global blacklist completely
                action = payload.get("action")  # SHARED or UNSHARED

                await face_cache.invalidate_global_blacklist(db)
                print(f"✅ Global blacklist reloaded (action: {action})")

            elif "face.load_organization" in subject:
                # Explicit request to load org into cache
                org_id = payload.get("org_id")

                if org_id:
                    await face_cache.load_organization(org_id, db)
                    print(f"✅ Organization {org_id} loaded into cache")

        except Exception as e:
            print(f"⚠️  Cache event handler error: {e}")

    # Subscribe to Commands
    await nc.subscribe("commands.register_face", cb=command_handler)
    await nc.subscribe(config.SUBJECT, cb=message_handler)

    # Subscribe to Cache Events (invalidation)
    await nc.subscribe("events.face.>", cb=cache_event_handler)
    print("✅ Subscribed to cache invalidation events (events.face.*)")

    print("Listening for frames... Press Ctrl+C to exit.")

    # --- 5. Debug Stream Server (Aiohttp) ---
    latest_annotated_frames = {}

    from aiohttp import web, MultipartWriter

    async def mjpeg_handler(request):
        camera_id = request.match_info.get('camera_id')
        
        # Prepare Multipart Response
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'multipart/x-mixed-replace;boundary=frame',
                'Cache-Control': 'no-store, no-cache, must-revalidate, pre-check=0, post-check=0, max-age=0',
                'Pragma': 'no-cache',
                'Connection': 'close',
            }
        )
        await response.prepare(request)

        try:
            while True:
                if camera_id in latest_annotated_frames:
                    frame = latest_annotated_frames[camera_id]
                    # Encode to JPEG with high quality (96/100)
                    ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 96])
                    if ret:
                        frame_data = buffer.tobytes()
                        await response.write(
                            b'--frame\r\n'
                            b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n'
                        )

                # Cap at ~120 FPS (8.3ms per frame)
                await asyncio.sleep(0.0083) 
        except Exception:
            pass
        return response

    async def health_handler(request):
        """Health check endpoint for Docker"""
        return web.json_response({
            "status": "ok",
            "service": "inference",
            "models_loaded": True,
            "cache_enabled": face_cache is not None
        })

    async def mjpeg_by_slug_handler(request):
        """
        Stream MJPEG usando slugs (org/zone/camera_name)
        Ejemplo: /stream/vigias/planta/cam701/mjpeg
        """
        org_slug = request.match_info.get('org_slug')
        zone_slug = request.match_info.get('zone_slug')
        camera_name = request.match_info.get('camera_name')

        try:
            # Buscar cámara por org/zone/camera name
            query = """
                SELECT c.id
                FROM cameras c
                JOIN org_zones z ON c.zone_id = z.id
                JOIN organizations o ON z.organization_id = o.id
                WHERE o.slug = %s
                  AND z.slug = %s
                  AND (LOWER(c.name) LIKE %s OR c.id::text = %s)
                  AND c.is_active = true
                LIMIT 1
            """

            # Buscar por nombre (case-insensitive, partial match)
            search_pattern = f"%{camera_name.lower()}%"
            db.cur.execute(query, (org_slug, zone_slug, search_pattern, camera_name))
            result = db.cur.fetchone()

            if not result:
                return web.json_response({
                    "error": f"Camera not found: org={org_slug}, zone={zone_slug}, camera={camera_name}"
                }, status=404)

            camera_id = str(result[0])

            # Redirigir al handler principal con UUID
            # Crear un nuevo request con el camera_id
            request.match_info['camera_id'] = camera_id
            return await mjpeg_handler(request)

        except Exception as e:
            return web.json_response({
                "error": f"Error resolving camera: {str(e)}"
            }, status=500)

    async def cameras_list_handler(request):
        """
        Listar cámaras disponibles con sus URLs de stream
        """
        try:
            query = """
                SELECT
                    c.id,
                    c.name,
                    z.slug as zone_slug,
                    o.slug as org_slug,
                    c.is_active,
                    c.rtsp_url IS NOT NULL as has_rtsp
                FROM cameras c
                JOIN org_zones z ON c.zone_id = z.id
                JOIN organizations o ON z.organization_id = o.id
                WHERE c.is_active = true
                ORDER BY o.slug, z.slug, c.name
            """

            db.cur.execute(query)
            cameras = []

            for row in db.cur.fetchall():
                camera_id, name, zone_slug, org_slug, is_active, has_rtsp = row

                # Crear slug amigable del nombre (quitar espacios, lowercase)
                name_slug = name.lower().replace(' ', '-').replace('(', '').replace(')', '').replace('--', '-')

                cameras.append({
                    "id": str(camera_id),
                    "name": name,
                    "org": org_slug,
                    "zone": zone_slug,
                    "is_active": is_active,
                    "has_rtsp": has_rtsp,
                    "stream_urls": {
                        "by_uuid": f"/debug/{camera_id}/mjpeg",
                        "by_slug": f"/stream/{org_slug}/{zone_slug}/{name_slug}/mjpeg"
                    }
                })

            return web.json_response({
                "cameras": cameras,
                "total": len(cameras),
                "note": "Use stream_urls.by_slug for user-friendly URLs or stream_urls.by_uuid for direct access"
            })

        except Exception as e:
            return web.json_response({
                "error": str(e)
            }, status=500)

    async def test_rtsp_handler(request):
        """
        Test RTSP connection and return a single frame as base64.
        Payload: {"rtsp_url": "rtsp://..."}
        """
        try:
            data = await request.json()
            rtsp_url = data.get("rtsp_url")
            
            if not rtsp_url:
                 return web.json_response({"status": "error", "message": "Missing rtsp_url"}, status=400)

            # Run OpenCV in thread pool to avoid blocking
            def test_capture():
                cap = cv2.VideoCapture(rtsp_url)
                if not cap.isOpened():
                    return None
                
                # Try to read a frame
                ret, frame = cap.read()
                cap.release()
                
                if not ret or frame is None:
                    return None
                
                # Resize for preview (max width 640)
                h, w = frame.shape[:2]
                if w > 640:
                    scale = 640 / w
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                
                # Encode to JPEG
                ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if not ret:
                    return None
                    
                import base64
                # buffer is a numpy array.
                return base64.b64encode(buffer).decode('utf-8')

            b64_image = await asyncio.to_thread(test_capture)
            
            if b64_image:
                return web.json_response({
                    "status": "success", 
                    "message": "Connection successful",
                    "image": b64_image
                })
            else:
                return web.json_response({
                    "status": "error", 
                    "message": "Could not connect to stream or read frame"
                }, status=400)

        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    app = web.Application()
    app.router.add_get('/', health_handler)
    app.router.add_get('/health', health_handler)
    app.router.add_get('/cameras', cameras_list_handler)
    app.router.add_post('/test-rtsp', test_rtsp_handler)
    app.router.add_get('/debug/{camera_id}/mjpeg', mjpeg_handler)
    app.router.add_get('/stream/{org_slug}/{zone_slug}/{camera_name}/mjpeg', mjpeg_by_slug_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5000)
    await site.start()
    print("Debug Stream Server running on http://0.0.0.0:5000")

    try:
        # Loop forever
        while True:
             await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
        await nc.close()
        db.close()
        try:
            cv2.destroyAllWindows()
        except: pass

if __name__ == '__main__':
    try:
        import uvloop
        uvloop.install()
        print("uvloop installed.")
    except ImportError:
        print("uvloop not found, using default asyncio loop.")
    asyncio.run(run())
