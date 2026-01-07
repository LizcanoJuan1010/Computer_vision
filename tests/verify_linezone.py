import supervision as sv
import numpy as np

def test_line_zone_triggers():
    print("Testing sv.LineZone...")
    
    # Define a vertical line at x=100
    start = sv.Point(100, 0)
    end = sv.Point(100, 200)
    zone = sv.LineZone(start=start, end=end)
    
    print(f"Initial counts: In={zone.in_count}, Out={zone.out_count}")
    
    # Mock Detections
    # Frame 1: Object at (50, 100) - Left of line
    # Frame 2: Object at (150, 100) - Right of line (Crossed Left->Right)
    
    # Supervision expects detections with tracker_id for LineZone
    
    # Frame 1
    dets_1 = sv.Detections(
        xyxy=np.array([[40, 90, 60, 110]]),
        tracker_id=np.array([1])
    )
    zone.trigger(detections=dets_1)
    print(f"Frame 1 (Left): In={zone.in_count}, Out={zone.out_count}")
    
    # Frame 2
    dets_2 = sv.Detections(
        xyxy=np.array([[140, 90, 160, 110]]),
        tracker_id=np.array([1])
    )
    cross_result = zone.trigger(detections=dets_2)
    print(f"Frame 2 (Right): In={zone.in_count}, Out={zone.out_count}")
    print(f"Cross Result: {cross_result}")

if __name__ == "__main__":
    test_line_zone_triggers()
