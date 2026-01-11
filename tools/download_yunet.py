
import os
import requests
import shutil

# Model URL
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
TARGET_DIR = "inference/weights"
TARGET_FILE = "face_detection_yunet_2023mar.onnx"

def download_file(url, dest_folder, dest_filename):
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)
        print(f"Created directory: {dest_folder}")
    
    dest_path = os.path.join(dest_folder, dest_filename)
    
    if os.path.exists(dest_path):
        print(f"File {dest_filename} already exists. Skipping.")
        return

    print(f"Downloading {dest_filename} from {url}...")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(dest_path, 'wb') as f:
            shutil.copyfileobj(response.raw, f)
        print(f"Successfully downloaded {dest_filename} to {dest_path}")
    except Exception as e:
        print(f"Error downloading {dest_filename}: {e}")

if __name__ == "__main__":
    download_file(YUNET_URL, TARGET_DIR, TARGET_FILE)
