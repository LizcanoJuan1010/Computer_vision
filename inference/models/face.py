from insightface.app import FaceAnalysis
from ..config import config
from .base import BaseModel

class FaceModel(BaseModel):
    def __init__(self):
        self.app = None
        # Assuming model_name needs to be initialized if it's used as self.model_name
        # The original code used config.INSIGHTFACE_MODEL_NAME directly.
        # To make self.model_name available, it should be set.
        # I will add it here based on the original config usage.
        self.model_name = config.INSIGHTFACE_MODEL_NAME

    def load(self):
        print(f"Loading InsightFace model: {self.model_name}...")
        try:
            # Pass providers to both init and prepare to be safe
            self.app = FaceAnalysis(name=self.model_name, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
            self.app.prepare(ctx_id=0, det_size=(640, 640), det_thresh=0.15)
            print("InsightFace initialized.")
        except Exception as e:
            print(f"Error loading InsightFace model: {e}")
            raise e

    def predict(self, frames):
        if not self.app:
            raise Exception("Model not loaded")
        
        if isinstance(frames, list):
            # InsightFace app.get() is typically single-threaded CPU/GPU mix.
            # TODO: True batching requires accessing the underlying detection model directly.
            # For now, we process slightly faster by avoiding function call overhead?
            # Or just loop. 
            results = []
            for frame in frames:
                results.append(self.app.get(frame))
            return results
        else:
            return self.app.get(frames)
