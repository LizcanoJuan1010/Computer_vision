import sys
import os
import numpy as np
import cv2
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from inference.processors.spatial import SpatialAnalytics

def test_spatial_analytics():
    print("Testing SpatialAnalytics...")
    
    # 1. Initialize
    spatial = SpatialAnalytics()
    print("Initialized.")
    
    # Verify defaults are empty/None
    assert spatial.line_zones == [], "Default line_zones should be empty"
    assert spatial.polygon_zone is None, "Default polygon_zone should be None"
    print("Defaults verified.")
    
    # 2. Test Polyline Setup with Trigger
    points = [[100, 100], [200, 100], [200, 200]] # L-shape
    spatial.set_line_zone(points, trigger="in")
    assert len(spatial.line_zones) == 2, f"Should have 2 segments, got {len(spatial.line_zones)}"
    assert spatial.line_trigger == "in", f"Trigger should be 'in', got {spatial.line_trigger}"
    
    # Test Persistence (Bug Fix Verification)
    zone_id_before = id(spatial.line_zones[0])
    spatial.set_line_zone(points, trigger="in") # Call again with same args
    zone_id_after = id(spatial.line_zones[0])
    assert zone_id_before == zone_id_after, "LineZone object should persist if config is unchanged"
    print("Polyline setup with trigger and persistence verified.")
    
    # 3. Test Polygon Setup
    poly_points = [[10, 10], [50, 10], [50, 50], [10, 50]]
    spatial.set_polygon_zone(poly_points)
    assert spatial.polygon_zone is not None, "Polygon zone should be set"
    
    # Test Polygon Persistence
    poly_id_before = id(spatial.polygon_zone)
    spatial.set_polygon_zone(poly_points)
    poly_id_after = id(spatial.polygon_zone)
    assert poly_id_before == poly_id_after, "PolygonZone object should persist if config is unchanged"
    print("Polygon setup verified.")
    
    # 4. Test Update (Mocking YOLO results is hard without actual objects, 
    # but we can check if it runs without error on empty frame)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    
    # Mock YOLO results
    # We need a structure that mimics ultralytics Results
    # It's easier to just rely on the fact that if we pass something invalid it might crash,
    # but let's try to make a minimal valid mock.
    
    # Actually, sv.Detections.from_ultralytics expects a specific structure.
    # Let's skip the full update test for now and just verify the logic we changed (init and setters).
    # The update method relies on external libraries (supervision, ultralytics) which might be hard to mock perfectly here.
    
    print("Basic logic verified successfully.")

if __name__ == "__main__":
    test_spatial_analytics()
