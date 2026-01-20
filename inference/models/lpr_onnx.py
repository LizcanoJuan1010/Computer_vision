import os
import cv2
import numpy as np
import onnxruntime as ort
from .base import BaseModel
from ..config import config
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
        self.det_model_path = os.path.join(config.OCR_DET_MODEL_DIR,"det.onnx")
        self.rec_model_path = os.path.join(config.OCR_REC_MODEL_DIR,"rec.onnx")
        
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

        # Load Classification Model (Orientation)
        self.cls_model_path = config.OCR_CLS_MODEL_PATH
        self.cls_sess = None
        if os.path.exists(self.cls_model_path):
             try:
                # Force CPU for CLS (ShapeInferenceError on CUDA)
                providers = ['CPUExecutionProvider']
                sess_opts = ort.SessionOptions()
                sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
                try:
                    sess_opts.add_session_config_entry("session.disable_shape_inference", "1")
                except:
                    pass
                self.cls_sess = ort.InferenceSession(self.cls_model_path, sess_options=sess_opts, providers=providers)
                print(f"✅ LPR CLS (ONNX) loaded from {self.cls_model_path} on {self.cls_sess.get_providers()[0]}", flush=True)
             except Exception as e:
                print(f"❌ Failed to load CLS ONNX: {e}", flush=True)

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
                         if crop is None:
                             continue  # Skip this plate if crop failed
                        
                         # CLS: Check orientation
                         if self.cls_sess:
                             try:
                                 # Preprocess for CLS (3, 48, 192) Standard PP-OCR
                                 cls_input = self._preprocess_cls(crop)
                                 cls_input_name = self.cls_sess.get_inputs()[0].name
                                 cls_prob = self.cls_sess.run(None, {cls_input_name: cls_input})[0]
                                 
                                 # Output: [Batch, 2] (0:0deg, 1:180deg)
                                 # argmax
                                 idx = np.argmax(cls_prob[0])
                                 conf = cls_prob[0][idx]
                                 
                                 if idx == 1 and conf > 0.9: # 180 degrees
                                     print(f"🔄 Rotating Plate 180° (Conf: {conf:.2f})", flush=True)
                                     crop = cv2.rotate(crop, cv2.ROTATE_180)
                             except Exception as cls_e:
                                 print(f"⚠️ CLS Error: {cls_e}") 
                             
                         text, score = self._predict_rec(crop)
                         
                         result.all_texts.append((text, score))
                         
                         if score > conf and 4 <= len(text) <= 10: # Min 3 chars
                            has_letter = any(c.isalpha() for c in text)
                            has_digit = any(c.isdigit() for c in text)
                            if has_letter and has_digit:
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
        
        # 🌙 Night Vision Enhancement (Contrast Boost) - DISABLED FOR TEST
        """
        try:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            cl = clahe.apply(l)
            limg = cv2.merge((cl,a,b))
            img = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        except Exception:
            pass # Fallback to original
        """
            
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
        # Many ONNX exports from Paddle require Sigmoid manually
        raw_pred = outputs[0][0,0,:,:]
        pred = 1.0 / (1.0 + np.exp(-raw_pred))
        
        print(f"🔎 LPR Raw Max Score: {raw_pred.max():.4f} -> Prob Max: {pred.max():.4f}", flush=True) # DEBUG
        mask = pred > self.det_thresh
        
        boxes = self._boxes_from_bitmap(pred, mask, resize_w, resize_h)
        
        # Adjust scale and ensure 4 points
        scaled_boxes = []
        for box in boxes:
            # 1. Unclip (Expand)
            box = self._unclip(box, self.det_unclip_ratio)
            
            # 2. Get 4 corners (minAreaRect) AFTER expansion
            box = self._get_mini_boxes(box)
            
            box = box.reshape(-1, 2)
            box = box.astype(np.float32) 
            
            # 3. Resize back to original
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

        # The bitmap must be binary (0 or 255) for findContours
        bitmap = (_bitmap > self.det_thresh).astype(np.uint8) * 255
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
            if score < self.det_box_thresh:
                 continue
            
            # Return the points/contour directly, unclip + mini-box happens later
            boxes.append(points)
            
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

    def _preprocess_cls(self, img):
        # Resize to 48x192 (Standard for PP-OCR CLS Mobile v2)
        h, w = 48, 192
        resized = cv2.resize(img, (w, h))
        
        # Normalize (Mean/Std from PP-OCR)
        mean = np.array([0.5, 0.5, 0.5])
        std = np.array([0.5, 0.5, 0.5])
        
        img = resized.astype(np.float32) / 255.0
        img = (img - mean) / std
        
        # HWC -> CHW
        img = img.transpose(2, 0, 1)
        return np.expand_dims(img, axis=0).astype(np.float32)

    def _get_rotate_crop_image(self, img, points):
        """
        Rotate and crop image based on polygon points.
        Points must be 4 corners in order: top-left, top-right, bottom-right, bottom-left
        """
        try:
            # Ensure points is a numpy array with correct shape
            points = np.array(points, dtype=np.float32)
            
            # Validate we have exactly 4 points
            if points.shape != (4, 2):
                print(f"⚠️ LPR: Invalid points shape {points.shape}, expected (4, 2). Points: {points}", flush=True)
                # Try to get bounding rect instead
                if len(points) >= 4:
                    points = points[:4].reshape(4, 2)
                else:
                    return None
            
            # print(f"      📐 LPR Crop from {img.shape[1]}x{img.shape[0]} using points: {points.tolist()}", flush=True)
            
            # Check for degenerate polygons (zero area)
            width1 = np.linalg.norm(points[0] - points[1])
            width2 = np.linalg.norm(points[2] - points[3])
            height1 = np.linalg.norm(points[0] - points[3])
            height2 = np.linalg.norm(points[1] - points[2])
            
            img_crop_width = int(max(width1, width2))
            img_crop_height = int(max(height1, height2))
            
            # Ensure minimum dimensions
            if img_crop_width < 2 or img_crop_height < 2:
                print(f"⚠️ LPR: Crop too small ({img_crop_width}x{img_crop_height}), skipping", flush=True)
                return None
            
            # Build destination points
            pts_std = np.float32([
                [0, 0], 
                [img_crop_width, 0], 
                [img_crop_width, img_crop_height], 
                [0, img_crop_height]
            ])
            
            # Ensure points are contiguous float32 array
            points = np.ascontiguousarray(points, dtype=np.float32)
            pts_std = np.ascontiguousarray(pts_std, dtype=np.float32)
            
            M = cv2.getPerspectiveTransform(points, pts_std)
            dst_img = cv2.warpPerspective(img, M, (img_crop_width, img_crop_height), borderMode=cv2.BORDER_REPLICATE)
            
            # If vertical text, rotate
            if dst_img.shape[1] > 0 and float(dst_img.shape[0]) / float(dst_img.shape[1]) > 1.5:
                dst_img = np.rot90(dst_img)
            
            return dst_img
            
        except Exception as e:
            print(f"⚠️ LPR: Crop error: {e}", flush=True)
            return None

    # --- Internal Methods (Recognition) ---
    def _predict_rec(self, img_crop):
        try:
            # 1. Preprocess (Enhance & Resize)
            
            # --- PRE-PROCESSING IMPROVEMENTS (User Requested) ---
            # A. CLAHE (Contrast Limited Adaptive Histogram Equalization)
            # Helps with dark plates or shadows.
            try:
                # Convert to LAB to only enhance Lightness
                lab = cv2.cvtColor(img_crop, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                
                # Apply CLAHE to L-channel
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                cl = clahe.apply(l)
                
                # Merge and convert back
                limg = cv2.merge((cl, a, b))
                img_crop = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
            except Exception:
                pass # Fallback to original if enhancement fails

            h, w = img_crop.shape[:2]
            target_h = 48 # PP-OCRv4 uses 48
            target_w = 320
            
            # Resize maintaining aspect ratio, pad if needed
            ratio = w / float(h)
            resize_w = int(target_h * ratio)
            if resize_w > target_w:
                resize_w = target_w
            
            # B. Interpolation (Cubic for better sharpness on small crops)
            img_resize = cv2.resize(img_crop, (resize_w, target_h), interpolation=cv2.INTER_CUBIC)
            
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
        print(f"📖 LPR Decoded: '{text}' (Conf: {avg_conf:.4f})", flush=True)
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
        
        # Backup: Standard PaddleOCR Latin Dictionary (Approximate)
        # This list includes blank, then Chars.
        # But our _get_char implementation handles blank at index 0.
        # Most LPR models use Digits + Upper Case.
        res = list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ ")
        return res
