from .base import BaseModel

class LPRModel(BaseModel):
    def __init__(self):
        self.model = None

    def load(self):
        print("LPR Model (Stub): Initialized. Waiting for PaddleOCR implementation.")
        pass
    def predict(self, frame_or_batch, conf=0.4):
        # Return empty list to simulate no detections
        # Must return valid iterable (list of results) matching batch size
        if isinstance(frame_or_batch, list):
            return [StubResult() for _ in range(len(frame_or_batch))]
        return StubResult()

class StubResult:
    def __init__(self):
        self.boxes = []
        self.conf = []
        self.cls = []
