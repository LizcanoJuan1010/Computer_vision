import cv2
import sys

def check_res(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print("Error opening video")
        return
    
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Resolution: {width}x{height}")
    cap.release()

if __name__ == "__main__":
    check_res("test_video.mp4")
