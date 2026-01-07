import unittest
from unittest.mock import MagicMock
import time
from inference.processors.security import SecurityProcessor

class TestDebouncing(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_yolo = MagicMock()
        self.mock_yolo.predict.return_value = [MagicMock()] # Return list of 1 result
        self.mock_face = MagicMock()
        self.processor = SecurityProcessor(self.mock_db, self.mock_yolo, self.mock_face)
        
        # Mock SpatialAnalytics result
        self.mock_result = MagicMock()
        self.mock_result.annotated_frame = None
        self.mock_result.line_counts = (0, 0)
        self.mock_result.intrusion_events = []
        
        # Mock SpatialAnalytics instance
        self.mock_spatial = MagicMock()
        self.mock_spatial.update.return_value = self.mock_result
        
        # Inject mock via _spatial_mock
        self.processor._spatial_mock = {"test_cam": self.mock_spatial}

    def test_debouncing(self):
        camera_id = "test_cam"
        config = {"features": ["intrusion"], "debounce_seconds": 2.0}
        
        # 1. First Detection (Should Alert)
        # 1. First Detection (Should Alert)
        import numpy as np
        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        self.mock_result.intrusion_events = [101]
        self.processor.process_batch([dummy_frame], [camera_id], [config])
        
        self.mock_db.save_event.assert_called_once()
        self.mock_db.save_event.reset_mock()
        
        # 2. Immediate Second Detection (Should be Debounced)
        self.mock_result.intrusion_events = [101] # Still detecting
        self.processor.process_batch([dummy_frame], [camera_id], [config])
        self.mock_db.save_event.assert_not_called()
        
        # 3. Wait > debounce_seconds (Should Alert again)
        time.sleep(2.1)
        self.mock_result.intrusion_events = [101] # Still detecting
        self.processor.process_batch([dummy_frame], [camera_id], [config])
        self.mock_db.save_event.assert_called_once()

if __name__ == '__main__':
    unittest.main()
