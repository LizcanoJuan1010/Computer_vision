from .base import BaseModel
try:
    from paddleocr import PaddleOCR
    HAS_OCR = True
except ImportError:
    HAS_OCR = False
    print("⚠️ PaddleOCR not found. LPR will be disabled.")

class LPRModel(BaseModel):
    def __init__(self):
        self.model = None

    def load(self):
        if not HAS_OCR:
            print("❌ LPR Model: PaddleOCR missing.")
            return

        print("LPR Model: Loading PaddleOCR (English)...")
        # Global instance to avoid reloading. 
        # use_angle_cls=True for better accuracy on tilted plates
        # lang='en' is standard for alphanumeric plates
        self.model = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
        print("LPR Model: Loaded.")

    def predict(self, frame_or_batch, conf=0.45):
        if not self.model: 
            return StubResult()

        # Handle batch or single frame
        frames = frame_or_batch if isinstance(frame_or_batch, list) else [frame_or_batch]
        results = []

        for frame in frames:
            try:
                # PaddleOCR expects numpy array (H, W, C)
                # Returns: [[[[x1,y1],[x2,y2]...], (text, confidence)], ...]
                ocr_res = self.model.ocr(frame, cls=True)
                
                # Filter for best Plate-like text
                best_text = None
                best_conf = 0.0
                
                # Verify ocr_res structure (it can be None or list of lists)
                if ocr_res and ocr_res[0]:
                    for line in ocr_res[0]:
                        text, score = line[1]
                        # Simple Heuristic: Plates usually 5-8 chars, alphanumeric
                        # Adjust as needed for specific region
                        if score > conf and len(text) >= 4: 
                            if score > best_conf:
                                best_conf = score
                                best_text = text
                
                res = StubResult()
                if best_text:
                    res.label = best_text
                    res.conf = best_conf
                results.append(res)
                
            except Exception as e:
                print(f"LPR Error: {e}")
                results.append(StubResult())

        if not isinstance(frame_or_batch, list):
            return results[0]
        return results

class StubResult:
    def __init__(self):
        self.boxes = []
        self.conf = 0.0
        self.cls = []
        self.label = None # Plate Text
