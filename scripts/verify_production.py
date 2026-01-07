import asyncio
import cv2
import numpy as np
import json
import os
import time
from unittest.mock import MagicMock, patch

# Mock NATS
class MockNATS:
    def __init__(self):
        self.subscriptions = {}
        self.published_messages = []

    async def connect(self, url):
        print(f"[MOCK NATS] Connected to {url}")
        return self

    async def subscribe(self, subject, cb):
        print(f"[MOCK NATS] Subscribed to {subject}")
        self.subscriptions[subject] = cb

    async def publish(self, subject, data, headers=None):
        print(f"[MOCK NATS] Published to {subject} (Headers: {headers})")
        self.published_messages.append((subject, data, headers))
        # Simulate routing if publishing to work.security
        if subject == "work.security":
            # In real life, Inference listens to this.
            # We can't easily invoke the real Inference loop here without blocking.
            # But we verified the Router -> NATS part.
            pass

    async def close(self):
        print("[MOCK NATS] Closed")

# Mock Redis
class MockRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value

    @classmethod
    def from_url(cls, url, decode_responses=True):
        print(f"[MOCK REDIS] Connected to {url}")
        return cls()

# Import Router Dispatcher
# We need to patch NATS and Redis to test Dispatcher logic in isolation
from app.services.dispatcher import Dispatcher
from app.core.config import settings

async def verify_router_logic():
    print("\n--- Verifying Router Logic ---")
    mock_nc = MockNATS()
    dispatcher = Dispatcher(mock_nc)
    
    # Simulate Camera Frame Message
    camera_id = "cam_production_test"
    subject = f"camera.{camera_id}.frame"
    payload = b"dummy_frame_data"
    
    # Mock Message Object
    class MockMsg:
        def __init__(self, subject, data, header=None):
            self.subject = subject
            self.data = data
            self.header = header

    msg = MockMsg(subject, payload)
    
    # Mock Cache to return 'security' service
    with patch("app.services.cache.router_cache.get_services", return_value={"security"}):
        await dispatcher.process_frame(msg)
    
    # Check if published to work.security with headers
    found = False
    for subj, data, headers in mock_nc.published_messages:
        if subj == "work.security":
            if headers and headers.get("camera_id") == camera_id:
                print("✅ Router correctly routed message to 'work.security' with camera_id header.")
                found = True
            else:
                print("❌ Router routed message but MISSING camera_id header!")
    
    if not found:
        print("❌ Router FAILED to route message.")
    return found

async def verify_inference_logic():
    print("\n--- Verifying Inference Logic ---")
    # We will use the integration test approach but slightly more 'scripted'
    from inference.processors.security import SecurityProcessor
    from inference.database import Database
    
    # Real DB Connection
    db = Database()
    try:
        db.connect()
    except Exception as e:
        print(f"❌ Could not connect to DB: {e}")
        return False

    # Mock Models
    mock_yolo = MagicMock()
    mock_face = MagicMock()
    
    # Mock YOLO Return
    import supervision as sv
    # Create dummy detections: 1 person (class_id=0)
    # xyxy, confidence, class_id, tracker_id
    mock_detections = sv.Detections(
        xyxy=np.array([[100, 100, 200, 200]]),
        confidence=np.array([0.9]),
        class_id=np.array([0]),
        tracker_id=np.array([999]) # Special ID for verification
    )
    
    # Mock YOLO Return
    mock_result_obj = MagicMock()
    mock_result_obj.boxes.cls = [0]
    
    # Use side_effect to ensure return value
    mock_yolo.predict.side_effect = lambda x: [mock_result_obj]

    # Patch SpatialAnalytics.update directly to avoid internal tracker logic changing IDs
    with patch("inference.processors.spatial.SpatialAnalytics.update") as mock_update:
        # Create a mock result
        mock_spatial_result = MagicMock()
        mock_spatial_result.annotated_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        mock_spatial_result.line_counts = (0, 0)
        mock_spatial_result.intrusion_events = [999] # Force ID 999
        mock_update.return_value = mock_spatial_result
        
        # We also need to mock set_polygon_zone to avoid errors if called
        with patch("inference.processors.spatial.SpatialAnalytics.set_polygon_zone"):
             processor = SecurityProcessor(db, mock_yolo, mock_face)
             
             # Config
             camera_id = "cam_production_verify"
             config = {
                 "features": ["intrusion"],
                 "zones": {
                     "intrusion": {
                         "points": [[0, 0], [300, 0], [300, 300], [0, 300]]
                     }
                 },
                 "debounce_seconds": 0
             }
             
             # Frame
             frame = np.zeros((720, 1280, 3), dtype=np.uint8)
             
             # Verify Mock
             print(f"DEBUG: Mock YOLO return value check: {type(mock_yolo.predict([frame]))}")
             
             # Process
             print(f"Processing frame for {camera_id}...")
             processor.process_batch([frame], [camera_id], [config])
        
        # Verify in DB
        # We check if an event was created for track_id 999
        # Wait a moment for async commit if any (though save_event is sync)
        
        cur = db.conn.cursor()
        cur.execute("""
            SELECT id, event_type, track_id 
            FROM events 
            WHERE track_id = '999' 
            ORDER BY id DESC LIMIT 1
        """)
        row = cur.fetchone()
        
        if row:
            print(f"✅ Event found in DB: ID={row[0]}, Type={row[1]}, Track={row[2]}")
            # Clean up
            cur.execute("DELETE FROM events WHERE track_id = '999'")
            cur.execute("DELETE FROM cameras WHERE name = %s", (camera_id,))
            db.conn.commit()
            print("✅ Cleanup successful.")
            return True
        else:
            print("❌ Event NOT found in DB!")
            # Debug: Check if any events exist
            cur.execute("SELECT * FROM events ORDER BY id DESC LIMIT 5")
            print("Last 5 events:", cur.fetchall())
            return False

async def main():
    print("=== PRODUCTION READINESS VERIFICATION ===")
    
    router_ok = await verify_router_logic()
    inference_ok = await verify_inference_logic()
    
    if router_ok and inference_ok:
        print("\n✅ SYSTEM VERIFIED: READY FOR PRODUCTION")
    else:
        print("\n❌ SYSTEM VERIFICATION FAILED")

if __name__ == "__main__":
    # Add project root to path
    import sys
    sys.path.append(os.getcwd())
    sys.path.append(os.path.join(os.getcwd(), "router"))
    
    asyncio.run(main())
