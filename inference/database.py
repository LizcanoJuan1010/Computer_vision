import psycopg2
from psycopg2.extras import execute_values
from .config import config
import queue
import threading
import time
import numpy as np
import json

class Database:
    def __init__(self):
        self.conn = None
        self.cur = None

        # Async Write Queue
        self.write_queue = queue.Queue()
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)

        # In-Memory Cache
        self.known_face_embeddings = []
        self.known_face_names = []
        self.camera_uuid_cache = {} # {name: uuid}

    def connect(self):
        try:
            print(f"Connecting to DB: {config.DB_CONN_STR}")
            self.conn = psycopg2.connect(config.DB_CONN_STR)
            # Remove persistent cursor
            # self.cur = self.conn.cursor()
            self._init_schema()
            self.load_faces()
            print("Database connected, schema initialized, and faces loaded.")

            # Start Worker
            self.worker_thread.start()

        except Exception as e:
            print(f"Database connection error: {e}")
            raise

    def _init_schema(self):
        """
        Schema initialization - now managed by database/schema.sql with UUIDs.
        """
        with self.conn.cursor() as cur:
            # Enable required extensions
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

        self.conn.commit()
        print("✅ Extensions verified. Schema managed by schema.sql (UUIDs)")

    def load_faces(self):
        """Loads all faces from DB into memory."""
        try:
            print("Loading faces into memory...")
            with self.conn.cursor() as cur:
                cur.execute("SELECT name, embedding FROM faces")
                rows = cur.fetchall()

            embeddings = []
            names = []

            for name, emb_str in rows:
                if isinstance(emb_str, str):
                    emb = np.array(json.loads(emb_str), dtype=np.float32)
                else:
                    emb = np.array(emb_str, dtype=np.float32)

                embeddings.append(emb)
                names.append(name)

            if embeddings:
                self.known_face_embeddings = np.stack(embeddings)
                self.known_face_names = np.array(names)
                # Normalize for cosine similarity
                norm = np.linalg.norm(self.known_face_embeddings, axis=1, keepdims=True)
                self.known_face_embeddings = self.known_face_embeddings / (norm + 1e-10)

            print(f"Loaded {len(names)} faces.")
        except Exception as e:
            print(f"Error loading faces: {e}")

    # ... (find_nearest_face remains same) ...
    def find_nearest_face(self, embedding): # Now In-Memory!
        if len(self.known_face_embeddings) == 0:
            return None

        # Normalize input
        embedding = embedding / (np.linalg.norm(embedding) + 1e-10)

        # Cosine Similarity (Dot product of normalized vectors)
        # Result is -1 to 1. 1 is identical.
        similarities = np.dot(self.known_face_embeddings, embedding)

        best_idx = np.argmax(similarities)
        best_score = similarities[best_idx]

        # Convert similarity to "distance" (0=same, 1=ortho, 2=opposite)
        # distance = 1 - similarity
        distance = 1.0 - best_score

        return (self.known_face_names[best_idx], distance)

    def _worker_loop(self):
        """Background thread to handle DB writes."""
        print("DB Worker started.")
        while self.running:
            try:
                # Get task with timeout to allow checking self.running
                task = self.write_queue.get(timeout=1.0)
                type_, data = task

                try:
                    if type_ == "stats":
                        self._save_stats_sync(*data)
                    elif type_ == "event":
                        self._save_event_sync(*data)
                except Exception as e:
                    print(f"DB Worker Error ({type_}): {e}")
                    self.conn.rollback()
                finally:
                    self.write_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                print(f"DB Worker Fatal Error: {e}")

    def save_stats(self, camera_id, in_count, out_count):
        self.write_queue.put(("stats", (camera_id, in_count, out_count)))

    def _save_stats_sync(self, camera_name, in_count, out_count):
        """
        Save camera stats. Now uses UUID foreign key to cameras.
        """
        camera_uuid = self.get_camera_uuid(camera_name)
        if not camera_uuid:
            print(f"⚠️  Could not resolve UUID for camera: {camera_name}")
            return

        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO camera_stats (camera_id, in_count, out_count)
                VALUES (%s, %s, %s)
            """, (camera_uuid, in_count, out_count))
        self.conn.commit()

    def get_camera_uuid(self, camera_name):
        """
        Get UUID for camera by name. 
        """
        # Check cache first
        if camera_name in self.camera_uuid_cache:
            return self.camera_uuid_cache[camera_name]

        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT id FROM cameras WHERE name = %s", (camera_name,))
                res = cur.fetchone()
                if res:
                    self.camera_uuid_cache[camera_name] = res[0]
                    return res[0]

                # Camera doesn't exist, create it
                cur.execute("""
                    INSERT INTO cameras (name, rtsp_url)
                    VALUES (%s, 'rtsp://placeholder')
                    RETURNING id
                """, (camera_name,))
                new_id = cur.fetchone()[0]
            
            self.conn.commit()
            self.camera_uuid_cache[camera_name] = new_id
            print(f"✅ Created new camera with UUID: {camera_name} -> {new_id}")
            return new_id
        except Exception as e:
            print(f"Error resolving camera UUID: {e}")
            self.conn.rollback()
            return None

    def get_camera_config_from_db(self, camera_identifier):
        """
        Fetch full camera config from DB including zone and AI settings.
        """
        try:
            # 1. Resolve UUID if name provided
            import uuid
            try:
                cam_uuid = str(uuid.UUID(camera_identifier))
            except ValueError:
                # Proceed assuming it's a name
                cam_uuid = self.get_camera_uuid(camera_identifier)
                if not cam_uuid:
                    return None
                cam_uuid = str(cam_uuid)

            # 2. Query DB for Config + Zone + Org
            query = """
                SELECT 
                    c.id, c.name, 
                    z.slug as zone_slug,
                    o.slug as org_slug, o.id as org_id,
                    json_agg(json_build_object(
                         'event_type', ac.event_type,
                         'confidence', ac.confidence_threshold,
                         'roi', ac.roi_polygon,
                         'severity', ac.default_severity
                    )) as ai_configs
                FROM cameras c
                JOIN org_zones z ON c.zone_id = z.id
                JOIN organizations o ON z.organization_id = o.id
                LEFT JOIN camera_ai_configs ac ON c.id = ac.camera_id AND ac.is_active = true
                WHERE c.id = %s
                GROUP BY c.id, z.id, o.id
            """
            
            with self.conn.cursor() as cur:
                cur.execute(query, (cam_uuid,))
                row = cur.fetchone()
            
            if not row:
                return None
                
            cam_id, name, zone_slug, org_slug, org_id, ai_configs = row
            
            # 3. Construct Config Object
            config = {
                "camera_id": cam_id,
                "name": name,
                "org_slug": org_slug,
                "org_id": str(org_id),
                "zone_slug": zone_slug,
                # "is_restricted_zone": is_restricted, # REMOVED
                # "auto_save_unknown": auto_save, # REMOVED
                "features": [],
                "zones": {},
                # Default thresholds
                "face_config": {"threshold": 0.6},
                "intrusion_config": {"debounce": 60}
            }
            
            # Process AI Configs (Turn into features list and config dicts)
            if ai_configs and ai_configs[0]['event_type'] is not None:
                for ac in ai_configs:
                    etype = ac['event_type']
                    if etype not in config["features"]:
                        config["features"].append(etype)
                    
                    # Store zone polygon
                    if etype not in config["zones"]:
                         config["zones"][etype] = {}
                    
                    if ac.get('roi'):
                        config["zones"][etype]["points"] = ac['roi']
                        
                    # Face specific config
                    if etype == 'face_recognition' and ac.get('face_threshold'):
                         config["face_config"]["threshold"] = float(ac['face_threshold'])
                         if "face" not in config["features"]: config["features"].append("face")

            # Fallback/Default features if empty (Legacy support)
            if not config["features"]:
                config["features"] = ["face", "intrusion"]
                
            return config

        except Exception as e:
            print(f"Error fetching camera config from DB: {e}")
            self.conn.rollback()
            return None

    def _save_event_sync(self, camera_name, event_type, track_id, confidence, bbox, severity):
        """
        Save event to database. Now uses UUID for camera_id and ENUM for severity/status.
        """
        camera_uuid = self.get_camera_uuid(camera_name)
        if not camera_uuid:
            return

        bbox_json = json.dumps(bbox) if bbox else None

        # Cast severity to enum explicitly
        try:
            # print(f"DEBUG: Attempting to insert event for {camera_uuid}, Type={event_type}")
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO events (
                        camera_id, event_type, track_id, confidence, bbox, severity, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::event_severity_enum, %s::event_status_enum)
                """, (camera_uuid, event_type, str(track_id), confidence, bbox_json, severity, 'PENDING'))

            self.conn.commit()
            # print(f"Event saved for {camera_name}: {event_type} (Track {track_id})")
        except Exception as e:
            print(f"CRITICAL DB ERROR saving event: {e}")
            self.conn.rollback()
            raise e

    def close(self):
        self.running = False
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)

        # Removed self.cur.close() as it's no longer used
        if self.conn:
            self.conn.close()
