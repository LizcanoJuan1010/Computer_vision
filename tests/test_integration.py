import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import cv2
import time
from inference.processors.security import SecurityProcessor
from inference.database import Database
from inference.config import config

class TestIntegration(unittest.TestCase):
    def setUp(self):
        # 1. Setup Database (Mocked for safety, or Real if needed)
        # We will mock the DB connection to avoid dependency on running DB container for this test,
        # but we verify the logic flow.
        self.mock_db = MagicMock()
        
        # 2. Setup Models (Mocked)
        self.mock_yolo = MagicMock()
        self.mock_face = MagicMock()
        
        # Mock YOLO Results
        # We need to simulate what ultralytics returns so SpatialAnalytics can consume it
        # However, sv.Detections.from_ultralytics is hard to mock perfectly without real objects.
        # So we will mock the SpatialAnalytics.update method to avoid complex dependency mocking
        # and focus on the SecurityProcessor -> DB flow.
        
        # Wait, the user wants to verify "everything connects". 
        # So mocking SpatialAnalytics might hide issues in SpatialAnalytics integration.
        # Let's try to use real SpatialAnalytics but mock the YOLO input.
        
        self.mock_lpr = MagicMock()
        # pp_human, face, lpr
        self.processor = SecurityProcessor(self.mock_db, self.mock_yolo, self.mock_face, self.mock_lpr)

    def test_end_to_end_flow(self):
        # Mock PP-Human predict return
        # It generic result object (PPHumanResult)
        mock_result_obj = MagicMock()
        mock_result_obj.boxes = [[100, 100, 200, 200]] # XYXY
        mock_result_obj.conf = [0.9]
        mock_result_obj.cls = [0] # Person = 0
        mock_result_obj.id = [101] # Track ID
        mock_result_obj.actions = {} # No actions for this test
        
        self.mock_yolo.predict.return_value = [mock_result_obj] # mock_yolo is technically pp_human mock
        
        # Setup Config
        camera_id = "test_cam_integration"
        # Person center is (150, 150)
        # Zone: Square (0,0) to (300,300)
        config_data = {
            "features": ["intrusion"],
            "zones": {
                "intrusion": {
                    "points": [[0, 0], [300, 0], [300, 300], [0, 300]]
                }
            },
            "debounce_seconds": 0
        }
        
        # Create Dummy Frame
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        
        # Run Process
        self.processor.process_batch([frame], [camera_id], [config_data])
        
        # Verify DB Save Event was called
        # The save_event signature in security.py is: save_event(camera_id, type, track_id, severity=...)
        # In test check 'camera_name' vs 'camera_id'. The mock probably captures positional args.
        self.mock_db.save_event.assert_called_once()
        args, kwargs = self.mock_db.save_event.call_args
        
        # SecurityProcessor calls: self.db.save_event(camera_id, "intrusion", tid, severity="HIGH")
        # args[0] = camera_id
        # args[1] = "intrusion"
        # args[2] = tid
        
        self.assertEqual(args[0], camera_id)
        self.assertEqual(args[1], "intrusion")
        self.assertEqual(args[2], 101) # Track ID
        
        print("Integration Test Passed: Flow from Frame -> PP-Human(mock) -> Spatial -> Alert -> DB(mock) verified.")

if __name__ == '__main__':
    unittest.main()
