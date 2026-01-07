from huggingface_hub import hf_hub_download
import os
import shutil

# Repository and file
repo_id = "insomneyl/yolo11-placas-colombia"
filename = "weights/best.pt"
target_name = "placas_colombia.pt"
target_dir = "../inference/weights" # Relative to this script

print(f"Downloading {filename} from {repo_id}...")

try:
    model_path = hf_hub_download(repo_id=repo_id, filename=filename)
    print(f"Downloaded to cache: {model_path}")
    
    # Ensure target dir exists
    abs_target_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), target_dir)
    os.makedirs(abs_target_dir, exist_ok=True)
    
    dest_path = os.path.join(abs_target_dir, target_name)
    
    shutil.copy(model_path, dest_path)
    print(f"Model saved to: {dest_path}")
    
except Exception as e:
    print(f"Error downloading model: {e}")
    exit(1)
