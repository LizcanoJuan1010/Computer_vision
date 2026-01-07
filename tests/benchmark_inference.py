import time
import cv2
import numpy as np
import torch
from inference.models.yolo import YOLOModel

def benchmark():
    print("Initializing YOLO Model...")
    model = YOLOModel()
    model.load()
    
    # Create dummy frame (1080p)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    
    batch_sizes = [1, 4, 8, 16]
    
    print("\nStarting Benchmark...")
    print(f"{'Batch Size':<12} | {'FPS':<10} | {'Latency (ms)':<15}")
    print("-" * 45)
    
    for batch_size in batch_sizes:
        batch = [frame] * batch_size
        
        # Warmup
        for _ in range(5):
            model.predict(batch)
            
        start_time = time.time()
        iterations = 50
        
        for _ in range(iterations):
            model.predict(batch)
            
        total_time = time.time() - start_time
        total_frames = iterations * batch_size
        fps = total_frames / total_time
        latency = (total_time / iterations) * 1000 # Latency per batch
        
        print(f"{batch_size:<12} | {fps:<10.2f} | {latency:<15.2f}")

if __name__ == "__main__":
    benchmark()
