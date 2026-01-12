"""
LPR Model - License Plate Recognition using PP-OCRv4 Server
Uses high-accuracy server models for detection and recognition
"""
import os
from .base import BaseModel

try:
    from paddleocr import PaddleOCR
    HAS_OCR = True
except ImportError:
    HAS_OCR = False
    print("⚠️ PaddleOCR not found. LPR will be disabled.")


class LPRResult:
    """Result container for LPR"""
    def __init__(self):
        self.boxes = []     # [[x1,y1,x2,y2], ...]
        self.conf = 0.0
        self.cls = []
        self.label = None   # Plate text
        self.all_texts = [] # All detected texts with confidence


class LPRModel(BaseModel):
    """
    License Plate Recognition using PP-OCRv4 Server Models
    
    Uses:
    - Detection: ch_PP-OCRv4_det_server (best for rectangular boxes)
    - Recognition: en_PP-OCRv4_rec_server (English alphanumeric)
    - Classification: ch_ppocr_mobile_v2.0_cls (angle correction)
    """
    
    def __init__(self):
        self.model = None
        # Paths to downloaded server models
        self.det_model_dir = "/app/weights/ocr/det"
        self.rec_model_dir = "/app/weights/ocr/rec"
        self.cls_model_dir = "/app/weights/ocr/cls"

    def load(self):
        if not HAS_OCR:
            print("❌ LPR Model: PaddleOCR missing.", flush=True)
            return

        print("🚀 LPR Model: Loading PP-OCRv4 Server...", flush=True)
        
        # Check if server models exist
        use_server = os.path.exists(os.path.join(self.det_model_dir, "inference.pdmodel")) or \
                     os.path.exists(os.path.join(self.det_model_dir, "model.pdmodel"))
        
        if use_server:
            print("✅ Using PP-OCRv4 Server models", flush=True)
            try:
                self.model = PaddleOCR(
                    use_angle_cls=True,
                    lang='en',
                    det_model_dir=self.det_model_dir,
                    rec_model_dir=self.rec_model_dir,
                    cls_model_dir=self.cls_model_dir
                )
            except Exception as e:
                print(f"❌ PaddleOCR Init Error: {e}", flush=True)
                raise e
            print("✅ PaddleOCR Init Success", flush=True)
        else:
            print("⚠️ Server models not found, using default mobile models", flush=True)
            self.model = PaddleOCR(
                use_angle_cls=True,
                lang='en'
            )
            
        print("✅ LPR Model: Loaded.", flush=True)

    def predict(self, frame_or_batch, conf=0.45):
        """
        Run OCR on frame(s) to extract license plate text
        
        Args:
            frame_or_batch: Single frame or list of frames (numpy arrays)
            conf: Minimum confidence threshold
            
        Returns:
            LPRResult or list of LPRResult
        """
        if not self.model:
            return LPRResult()

        # Handle batch or single frame
        frames = frame_or_batch if isinstance(frame_or_batch, list) else [frame_or_batch]
        results = []

        for frame in frames:
            result = LPRResult()
            
            try:
                # PaddleOCR expects numpy array (H, W, C)
                ocr_res = self.model.ocr(frame, cls=True)
                
                # Find best plate-like text
                best_text = None
                best_conf = 0.0
                all_texts = []
                
                if ocr_res and ocr_res[0]:
                    for line in ocr_res[0]:
                        box = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                        text, score = line[1]
                        
                        all_texts.append((text, score))
                        
                        # Plate heuristic: 4-10 chars, alphanumeric
                        if score > conf and 4 <= len(text) <= 10:
                            # Prefer texts with mixed letters and numbers
                            has_letter = any(c.isalpha() for c in text)
                            has_digit = any(c.isdigit() for c in text)
                            
                            if has_letter and has_digit:
                                if score > best_conf:
                                    best_conf = score
                                    best_text = text.upper().strip()
                                    # Convert box to [x1,y1,x2,y2]
                                    xs = [p[0] for p in box]
                                    ys = [p[1] for p in box]
                                    result.boxes = [[min(xs), min(ys), max(xs), max(ys)]]
                
                if best_text:
                    result.label = best_text
                    result.conf = best_conf
                result.all_texts = all_texts
                    
            except Exception as e:
                print(f"❌ LPR Error: {e}", flush=True)

            results.append(result)

        if not isinstance(frame_or_batch, list):
            return results[0]
        return results
