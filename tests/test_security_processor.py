import unittest
from unittest.mock import MagicMock
import numpy as np
import sys
import os

# --- ENVIRONMENT SETUP ---

# 1. Define Stubs for Result Classes (Missing in base.py)
class PPHumanResult:
    def __init__(self):
        self.boxes = []
        self.cls = []
        self.id = []
        self.conf = []
        self.actions = {}
        self.global_events = []
        self.reid_features = {}

class PPVehicleResult:
    def __init__(self):
        self.boxes = []
        self.cls = [] # 0=Car, 1=Truck, etc.
        self.conf = []
        self.plates = {} # {idx: text}

# 2. Inject Stubs into sys.modules to satisfy imports in 'main' or 'security' if they try to import them
sys.modules['inference.models.base'] = MagicMock()
sys.modules['models.base'] = MagicMock()
sys.modules['inference.models.base'].PPHumanResult = PPHumanResult
sys.modules['inference.models.base'].PPVehicleResult = PPVehicleResult
sys.modules['models.base'].PPHumanResult = PPHumanResult
sys.modules['models.base'].PPVehicleResult = PPVehicleResult

# 3. Mock Config to verify property access
mock_conf = MagicMock()
mock_conf.DEFAULT_LPR_CONFIDENCE = 0.6
mock_conf.SIMILARITY_THRESHOLD = 0.5
mock_conf.DEFAULT_INTRUSION_CLASSES = [0]
mock_conf.DEFAULT_LINE_CROSSING_CLASSES = [0]
mock_conf.DEFAULT_INTRUSION_DEBOUNCE = 5.0
sys.modules['app.config'] = MagicMock()
sys.modules['app.config'].config = mock_conf

# 4. Package Shim: Make /app a package 'app'
if not os.path.exists('/app/__init__.py'):
    with open('/app/__init__.py', 'w') as f:
        f.write('')
sys.path.insert(0, '/') 

# 5. Import Target
try:
    from app.processors.security import SecurityProcessor
except ImportError as e:
    print(f"❌ Import Failed: {e}")
    sys.exit(1)

# --- TESTS ---

class TestSecurityProcessor(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_yolo = MagicMock()
        self.mock_face = MagicMock()
        self.mock_vehicle = MagicMock()
        
        self.processor = SecurityProcessor(
            db=self.mock_db,
            yolo_model=self.mock_yolo,
            face_model=self.mock_face,
            vehicle_model=self.mock_vehicle
        )

    def test_process_batch_vehicle_lpr(self):
        # Setup Frames (H, W, C)
        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        frames = [frame]
        camera_ids = ["test_cam_1"]
        configs = [{"features": ["lpr"]}]
        
        # Mock Yolo Result (No Humans)
        yolo_res = PPHumanResult() 
        self.mock_yolo.predict.return_value = [yolo_res]
        
        # Mock Vehicle Result (1 Car with Plate)
        veh_res = PPVehicleResult()
        veh_res.boxes = [[100, 100, 200, 200]]
        veh_res.cls = [0] # Car
        veh_res.conf = [0.9]
        veh_res.plates = {0: "ABC-123"}
        self.mock_vehicle.predict.return_value = [veh_res]
        
        # Run
        processed_frames = self.processor.process_batch(frames, camera_ids, configs)
        
        # Assertions
        self.assertEqual(len(processed_frames), 1)
        
        # Verify LPR Event Save (Check cooldown logic in implementation)
        # security.py checks self.lpr_cooldowns. Should be empty on first run.
        args, _ = self.mock_db.save_event.call_args
        # args[0] = cam_id, args[1] = type, args[2] = text
        self.assertEqual(args[0], "test_cam_1")
        self.assertEqual(args[1], "lpr")
        self.assertEqual(args[2], "ABC-123")
        
        print("\n✅ test_process_batch_vehicle_lpr: PASSED")

    def test_process_batch_multiple(self):
         # Test batch processing stability
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frames = [frame, frame]
        camera_ids = ["cam1", "cam2"]
        configs = [{}, {}]
        
        # Mocks
        self.mock_yolo.predict.return_value = [PPHumanResult(), PPHumanResult()]
        self.mock_vehicle.predict.return_value = [PPVehicleResult(), PPVehicleResult()]
        
        processed = self.processor.process_batch(frames, camera_ids, configs)
        self.assertEqual(len(processed), 2)
        print("\n✅ test_process_batch_multiple: PASSED")

if __name__ == '__main__':
    unittest.main()
