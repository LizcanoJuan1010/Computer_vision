try:
    from nvidia.dali import pipeline_def, fn
    import nvidia.dali.types as types
    import paddle
    HAS_DALI = True
except ImportError:
    print("⚠️ NVIDIA DALI not found. Falling back to Mock/CPU mode (will fail if DALI required).")
    HAS_DALI = False

import av
import numpy as np
import time

class RTSPSource:
    def __init__(self, camera_urls, batch_size):
        """
        Manages PyAV containers for multiple RTSP streams.
        Yields batches of raw video packets (bytes).
        """
        self.camera_urls = camera_urls
        self.batch_size = batch_size
        self.containers = {} # camera_id -> av.Container
        self.current_batch_ids = [] # To store IDs for the current batch
        # Initialize connections
        self._connect_all()
        
    def _connect_all(self):
        for cid, url in self.camera_urls.items():
            try:
                # Open with low latency options
                options = {'rtsp_transport': 'tcp', 'fflags': 'nobuffer', 'flags': 'low_delay', 'stimeout': '5000000'}
                container = av.open(url, options=options)
                # Ensure stream exists
                if not container.streams.video:
                     raise ValueError("No video stream found")
                self.containers[cid] = container
                print(f"✅ DALI Source: Connected to {cid}")
            except Exception as e:
                print(f"⚠️ DALI Source: Failed to connect to {cid}: {e}")
                self.containers[cid] = None

    def __call__(self, sample_info=None):
        """
        Callback for DALI external_source.
        Must return a batch of data.
        Format: List of numpy arrays (uint8 bytes of packet).
        """
        batch_data = []
        batch_ids = []
        
        active_cids = [k for k, v in self.containers.items() if v is not None]
        
        if not active_cids:
             # Prevent DALI crash if no streams
             # Return dummy batch (will likely produce garbage but keeps pipe alive)
             dummy = np.zeros(1024, dtype=np.uint8) 
             return [dummy] * self.batch_size

        current_batch_count = 0
        
        # Simple policy: One frame per active camera per batch
        # This assumes batch_size >= active_cameras or we chunk it.
        # For simplicity: Round robin or just iterate active.
        
        for cid in active_cids:
            if current_batch_count >= self.batch_size:
                break
                
            container = self.containers[cid]
            try:
                # Fetch NEXT packet
                packet = next(container.demux(video=0))
                
                # Decode packet to get frames
                frames = packet.decode()
                if not frames:
                    continue # Packet contained no full frames yet
                
                # Take the first frame (most RTSP packets here are single frame)
                # Convert to RGB numpy
                frame = frames[0].to_ndarray(format='rgb24')
                
                batch_data.append(frame)
                batch_ids.append(cid)
                current_batch_count += 1
                
            except (StopIteration, Exception) as e:
                print(f"⚠️ Stream Error {cid}: {e}. Reconnecting...")
                self.containers[cid] = None 
        
        # Pad if necessary
        while len(batch_data) < self.batch_size:
            if batch_data:
                # Pad with copy
                batch_data.append(batch_data[-1])
                batch_ids.append(batch_ids[-1])
            else:
                # Total failure padding (black frame 640x640)
                batch_data.append(np.zeros((640, 640, 3), dtype=np.uint8)) 
                batch_ids.append("dummy")
                
        self.current_batch_ids = batch_ids
        return batch_data

@pipeline_def
def rtsp_pipeline(source_callback):
    # Get DECODED generic images (RGB) from source
    images = fn.external_source(source=source_callback, dtype=types.UINT8, layout="HWC")
    
    # Upload to GPU
    video = images.gpu()
    
    # Resize to uniform shape (Critical for batching)
    video = fn.resize(video, resize_x=640, resize_y=640)
    
    return video
