import os
import cv2
import numpy as np
import onnxruntime as ort
from .base import BaseModel

class LPRResult:
    """Result container for LPR"""
    def __init__(self):
        self.boxes = []     # [[x1,y1,x2,y2], ...]
        self.conf = 0.0
        self.label = None   # Plate text
        self.all_texts = [] # All detected texts with confidence

class LPRModelONNX(BaseModel):
    """
    License Plate Recognition using ONNX Runtime
    Replaces PaddleOCR to avoid compatibility crashes.
    """
    
    def __init__(self):
        self.det_sess = None
        self.rec_sess = None
        self.det_model_path = "/app/weights/ocr/det/det.onnx"
        self.rec_model_path = "/app/weights/ocr/rec/rec.onnx"
        
        # Preprocessing params for DBNet
        self.det_limit_side_len = 960
        self.det_thresh = 0.1 # SUPER LOW for debugging
        self.det_box_thresh = 0.3 # Lowered from 0.4
        self.det_unclip_ratio = 1.5

        # Rec params
        self.rec_img_shape = [3, 48, 320]
        
        # Dictionary
        self.char_list = self._load_dict()

    def load(self):
        print("🚀 LPR Model (ONNX): Loading...", flush=True)
        
        # Load Detection Model
        if os.path.exists(self.det_model_path):
            try:
                providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                self.det_sess = ort.InferenceSession(self.det_model_path, providers=providers)
                print(f"✅ LPR Detection (ONNX) loaded from {self.det_model_path}", flush=True)
            except Exception as e:
                print(f"❌ Failed to load Det ONNX: {e}", flush=True)
        else:
            print(f"⚠️ Det ONNX not found at {self.det_model_path}", flush=True)

        # Load Recognition Model
        if os.path.exists(self.rec_model_path):
            try:
                providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                self.rec_sess = ort.InferenceSession(self.rec_model_path, providers=providers)
                print(f"✅ LPR Recognition (ONNX) loaded from {self.rec_model_path}", flush=True)
            except Exception as e:
                print(f"❌ Failed to load Rec ONNX: {e}", flush=True)
        else:
            print(f"⚠️ Rec ONNX not found at {self.rec_model_path}. Text will not be read.", flush=True)

    def predict(self, frame_or_batch, conf=0.45):
        if not self.det_sess:
            return LPRResult() if not isinstance(frame_or_batch, list) else [LPRResult()]

        frames = frame_or_batch if isinstance(frame_or_batch, list) else [frame_or_batch]
        print(f"🚙 LPR: Predict called on {len(frames)} frames", flush=True)
        results = []

        for frame in frames:
            result = LPRResult()
            try:
                # 1. Detection
                boxes = self._predict_det(frame)
                print(f"    🔎 LPR Det: Found {len(boxes)} candidate plates", flush=True)
                
                # 2. Recognition (if enabled and boxes found)
                best_text = None
                best_conf = 0.0
                
                for box in boxes:
                     # Box is [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                     # Convert to rect for result
                     xs = [p[0] for p in box]
                     ys = [p[1] for p in box]
                     x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                     
                     result.boxes.append([x1, y1, x2, y2])

                     if self.rec_sess:
                         crop = self._get_rotate_crop_image(frame, np.array(box, dtype=np.float32))
                         text, score = self._predict_rec(crop)
                         
                         result.all_texts.append((text, score))
                         
                         if score > conf and len(text) >= 3: # Min 3 chars
                             if score > best_conf:
                                 best_conf = score
                                 best_text = text
                
                if best_text:
                    result.label = best_text
                    result.conf = best_conf
                    
            except Exception as e:
                print(f"❌ LPR Inference Error: {e}", flush=True)
                import traceback
                traceback.print_exc()
            
            results.append(result)

        if not isinstance(frame_or_batch, list):
            return results[0]
        return results

    # --- Internal Methods (Detection) ---
    def _predict_det(self, img):
        h, w = img.shape[:2]
        print(f"🔎 LPR Input Shape: {w}x{h}", flush=True) # DEBUG
        
        # 🌙 Night Vision Enhancement (Contrast Boost)
        # Convert to LAB, apply CLAHE to L-channel, merge back
        try:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            cl = clahe.apply(l)
            limg = cv2.merge((cl,a,b))
            img = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
            # print("🌙 LPR: Applied Night Vision CLAHE", flush=True) # DEBUG
        except Exception:
            pass # Fallback to original
            
        # Resize
        limit_side_len = self.det_limit_side_len
        ratio = 1.0
        if max(h, w) > limit_side_len:
            if h > w:
                ratio = float(limit_side_len) / h
            else:
                ratio = float(limit_side_len) / w
        resize_h = int(h * ratio)
        resize_w = int(w * ratio)
        
        # Ensure divisible by 32
        resize_h = max(int(round(resize_h / 32) * 32), 32)
        resize_w = max(int(round(resize_w / 32) * 32), 32)
        
        ratio_h = resize_h / float(h)
        ratio_w = resize_w / float(w)

        img_resize = cv2.resize(img, (resize_w, resize_h))
        
        # Normalize
        # mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
        # (img / 255.0 - mean) / std
        img_norm = img_resize.astype(np.float32) / 255.0
        img_norm -= np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1,1,3)
        img_norm /= np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1,1,3)
        
        # CHW
        img_input = img_norm.transpose(2, 0, 1)[np.newaxis, :]
        
        # Run ONNX
        input_name = self.det_sess.get_inputs()[0].name
        outputs = self.det_sess.run(None, {input_name: img_input})
        
        # Post-process (Simplified DB)
        # Output is often [1, 1, H, W] probability map
        pred = outputs[0][0,0,:,:]
        print(f"🔎 LPR Raw Max Score: {pred.max():.4f}", flush=True) # DEBUG
        mask = pred > self.det_thresh
        
        boxes = self._boxes_from_bitmap(pred, mask, resize_w, resize_h)
        
        # Adjust scale
        scaled_boxes = []
        for box in boxes:
            box = self._unclip(box, self.det_unclip_ratio)
            box = box.reshape(-1, 2)
            box = box.astype(np.float32) # Fix for numpy division error
            # Resize back
            box[:, 0] /= ratio_w
            box[:, 1] /= ratio_h
            
            # Clip to image
            box[:, 0] = np.clip(box[:, 0], 0, w)
            box[:, 1] = np.clip(box[:, 1], 0, h)
            
            if min(box[:, 0]) < max(box[:, 0]) and min(box[:, 1]) < max(box[:, 1]):
                scaled_boxes.append(box)
                
        return scaled_boxes

    def _boxes_from_bitmap(self, pred, _bitmap, dest_width, dest_height):
        # Using pyclipper for Unclip (DBNet standard)
        try:
           import pyclipper
           from shapely.geometry import Polygon
        except ImportError:
           print("Missing pyclipper/shapely", flush=True)
           return []

        bitmap = _bitmap.astype(np.uint8)
        outs = cv2.findContours(bitmap, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        if len(outs) == 2:
            contours = outs[0]
        else:
            contours = outs[1]
            
        boxes = []
        for contour in contours:
            points = contour.reshape((-1, 2))
            if len(points) < 3: continue
            
            score = self._box_score_fast(pred, points)
            if score < self.det_box_thresh: continue
            
            box = self._get_mini_boxes(contour)
            if box is None: continue
            boxes.append(box)
            
        return boxes

    def _unclip(self, box, unclip_ratio):
        import pyclipper
        poly = box.reshape(-1, 2)
        # polygon = Polygon(poly)
        # area = polygon.area
        # length = polygon.length
        area = cv2.contourArea(poly)
        length = cv2.arcLength(poly, True)
        distance = area * unclip_ratio / length
        offset = pyclipper.PyclipperOffset()
        offset.AddPath(poly, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        expanded = offset.Execute(distance)
        if len(expanded) == 0: return box
        return np.array(expanded[0]).reshape(-1, 2)

    def _box_score_fast(self, bitmap, _box):
        h, w = bitmap.shape[:2]
        box = _box.copy()
        xmin = np.clip(np.floor(box[:, 0].min()).astype(int), 0, w - 1)
        xmax = np.clip(np.ceil(box[:, 0].max()).astype(int), 0, w - 1)
        ymin = np.clip(np.floor(box[:, 1].min()).astype(int), 0, h - 1)
        ymax = np.clip(np.ceil(box[:, 1].max()).astype(int), 0, h - 1)

        mask = np.zeros((ymax - ymin + 1, xmax - xmin + 1), dtype=np.uint8)
        box[:, 0] = box[:, 0] - xmin
        box[:, 1] = box[:, 1] - ymin
        cv2.fillPoly(mask, box.reshape(1, -1, 2).astype(np.int32), 1)
        return cv2.mean(bitmap[ymin:ymax+1, xmin:xmax+1], mask)[0]

    def _get_mini_boxes(self, contour):
        bounding_box = cv2.minAreaRect(contour)
        points = sorted(list(cv2.boxPoints(bounding_box)), key=lambda x: x[0])

        if points[1][1] > points[0][1]:
            index_1 = 0
            index_4 = 1
        else:
            index_1 = 1
            index_4 = 0
        if points[3][1] > points[2][1]:
            index_2 = 2
            index_3 = 3
        else:
            index_2 = 3
            index_3 = 2

        box = [points[index_1], points[index_2], points[index_3], points[index_4]]
        return np.array(box, dtype=np.float32)

    def _get_rotate_crop_image(self, img, points):
        img_crop_width = int(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])))
        img_crop_height = int(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2])))
        pts_std = np.float32([[0, 0], [img_crop_width, 0], [img_crop_width, img_crop_height], [0, img_crop_height]])
        M = cv2.getPerspectiveTransform(points, pts_std)
        dst_img = cv2.warpPerspective(img, M, (img_crop_width, img_crop_height), borderMode=cv2.BORDER_REPLICATE)
        
        # If vertical text?
        if float(dst_img.shape[0]) / float(dst_img.shape[1]) > 1.5:
             dst_img = np.rot90(dst_img)
        return dst_img

    # --- Internal Methods (Recognition) ---
    def _predict_rec(self, img_crop):
        try:
            # 1. Preprocess (Resize, Normalize)
            h, w = img_crop.shape[:2]
            target_h = 48 # PP-OCRv4 uses 48
            target_w = 320
            
            # Resize maintaining aspect ratio, pad if needed
            ratio = w / float(h)
            resize_w = int(target_h * ratio)
            if resize_w > target_w:
                resize_w = target_w
            
            img_resize = cv2.resize(img_crop, (resize_w, target_h))
            
            # Normalize
            img_norm = img_resize.astype(np.float32) / 255.0
            img_norm -= 0.5
            img_norm /= 0.5
            
            # Pad to target_w if needed (right padding)
            padding_w = target_w - resize_w
            img_padded = cv2.copyMakeBorder(img_norm, 0, 0, 0, padding_w, cv2.BORDER_CONSTANT, value=0)
            
            # CHW
            img_input = img_padded.transpose(2, 0, 1)[np.newaxis, :]
            
            # 2. Inference
            input_name = self.rec_sess.get_inputs()[0].name
            outputs = self.rec_sess.run(None, {input_name: img_input})
            preds = outputs[0] # [Batch, Time, Classes]
            
            # 3. Decode (CTC)
            text, score = self._ctc_decode(preds)
            return text, score
            
        except Exception as e:
            print(f"❌ Rec Error: {e}", flush=True)
            return "", 0.0

    def _ctc_decode(self, preds):
        """
        Greedy CTC Decoder.
        pred: [Batch, Time, Classes] (Batch=1)
        """
        pred_idxs = np.argmax(preds, axis=2)[0] # Take first from batch -> [Time]
        pred_scores = np.max(preds, axis=2)[0]
        
        text = ""
        conf_list = []
        
        # Blank typically 0 or N-1. In PaddleOCR, index 0 is sometimes ignored or used for blank
        ignored_tokens = [0] 
        
        last_idx = -1
        
        decoded_out = []
        for i, idx in enumerate(pred_idxs):
            if idx in ignored_tokens: # Blank
                last_idx = idx
                continue
            if idx != last_idx:
                # New char
                char = self._get_char(idx)
                if char:
                    decoded_out.append(char)
                    conf_list.append(pred_scores[i])
            last_idx = idx
            
        text = "".join(decoded_out)
        avg_conf = sum(conf_list) / len(conf_list) if conf_list else 0.0
        return text, avg_conf

    def _get_char(self, idx):
        # Note: idx=0 is blank, so we often subtract 1 if the dict is 1-indexed?
        # PaddleOCR keys file usually starts from the first char (index 0 for blank is implicit in CTC).
        # But if the output classes include 0, maybe 0 is blank.
        # Let's assume idx is direct map to list where 0 was blank.
        # Actually, if 0 is blank, text-chars might start at 1.
        
        real_idx = idx - 1
        if real_idx < 0: return "" # Should be handled by ignored_tokens

        if real_idx >= len(self.char_list):
            return "" # Unknown
        return self.char_list[real_idx]

    def _load_dict(self):
        # Try to find a dict file
        dict_path = "/app/weights/ocr/rec/en_dict.txt" 
        if os.path.exists(dict_path):
             with open(dict_path, 'r') as f:
                 return [line.strip() for line in f.readlines()]
        
        # Backup: Generated printable chars.
        import string
        # Combining: digits + letters + punctuation
        # This list order must match model training.
        # Commonly: 0-9, then a-z, then A-Z, or interleaved.
        # For simplicity, we assume standard ASCII order, but this is a GUESS.
        return list(string.digits + string.ascii_lowercase + string.ascii_uppercase + string.punctuation)
