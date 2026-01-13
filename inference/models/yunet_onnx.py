
import numpy as np
import cv2
import onnxruntime as ort

class YuNetONNX:
    def __init__(self, model_path, input_size=(640, 640), 
                 conf_threshold=0.6, nms_threshold=0.3, top_k=5000,
                 backend_id=None, target_id=None):
        self.input_size = input_size # (w, h)
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self.top_k = top_k
        
        # Initialize ONNX Runtime
        # Initialize ONNX Runtime with robust fallback
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        try:
            self.session = ort.InferenceSession(model_path, providers=providers)
            active_providers = self.session.get_providers()
            print(f"✅ YuNet ONNX loaded. Providers: {active_providers}")
        except Exception as e:
            print(f"⚠️ Failed to load YuNet with CUDA: {e}")
            print("🔄 Falling back to CPUExecutionProvider...")
            try:
                self.session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
                print("✅ YuNet ONNX loaded on CPU (Fallback).")
            except Exception as e2:
                print(f"❌ Failed to load YuNet on CPU: {e2}")
                raise e2

        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        
        # Generate priors (anchors) only updates if input size changes
        self._input_h, self._input_w = 0, 0
        self.priors = None

    def setInputSize(self, size):
        # size is (w, h)
        if self.input_size != size:
            self.input_size = size
            # Invalidate priors
            self.priors = None

    def _generate_priors(self, height, width):
        # Strides for YuNet usually 8, 16, 32
        strides = [8, 16, 32]
        feature_map_sizes = []
        for s in strides:
            feature_map_sizes.append((int(np.ceil(height / s)), int(np.ceil(width / s))))
            
        priors = []
        for idx, (h, w) in enumerate(feature_map_sizes):
            stride = strides[idx]
            for i in range(h):
                for j in range(w):
                    # cx, cy, s_x, s_y
                    # Note: exact anchor definition depends on model training
                    # Standard YuNet: just grid points?
                    # The official openCV Zoo YuNet implementation uses simple grid centers
                    priors.append([j * stride, i * stride, stride, stride])
        
        return np.array(priors, dtype=np.float32)

    def detect(self, img):
        """
        Mimics cv2.FaceDetectorYN.detect API
        Returns: (1, faces) where faces is [N, 15]
        Format: x1, y1, w, h, x_re, y_re, ... (5 landmarks), score
        """
        orig_h, orig_w = img.shape[:2]
        
        # CRITICAL FIX: YuNet ONNX model expects FIXED input size
        # The yunet.onnx model was compiled for 640x640 input
        target_w, target_h = 640, 640  # Model expected size
        
        # Resize image to fixed size for inference
        resized_img = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        
        # Update input size and priors for the RESIZED image
        if self.input_size != (target_w, target_h):
            self.setInputSize((target_w, target_h))
        
        if self.priors is None or self._input_h != target_h or self._input_w != target_w:
             self._input_h, self._input_w = target_h, target_w
             self.priors = self._generate_priors(target_h, target_w)

        # 2. Preprocess
        # BGR, HWC -> 1, 3, H, W
        blob = cv2.dnn.blobFromImage(resized_img, 1.0, (target_w, target_h), (0, 0, 0), swapRB=False, crop=False)
        
        # 3. Inference
        try:
            outputs = self.session.run(self.output_names, {self.input_name: blob})
        except Exception as e:
            print(f"YuNet ONNX Inference Error: {e}")
            return 1, None
        
        # outputs usually:
        # [0]: loc  [1, N, 14]  (cx, cy, w, h, 5 landmarks (x,y))
        # [1]: conf [1, N, 2]   (background, face)
        # [2]: iou  [1, N, 1]   (iou score)
        
        loc, conf, iou = None, None, None
        for o in outputs:
            if o.shape[-1] == 14: loc = o
            elif o.shape[-1] == 2: conf = o
            elif o.shape[-1] == 1: iou = o
            
        if loc is None or conf is None:
            print("❌ YuNet Output shapes mismatch expectations.")
            return 0, None

        # 4. Decode
        # Remove batch dim
        loc = loc[0]
        conf = conf[0]
        iou = iou[0]
        
        # Get scores (face class)
        cls_scores = conf[:, 1]
        iou_scores = iou[:, 0]
        
        # OpenCV impl: scores = conf[:, 1]
        
        scores = cls_scores
        
        # Filter by threshold
        mask = scores > self.conf_threshold
        
        loc_v = loc[mask]
        scores_v = scores[mask]
        priors_v = self.priors[mask]
        
        if len(scores_v) == 0:
            return 0, None
            
        # Decode boxes
        # priors: [cx_grid, cy_grid, stride, stride]
        # loc: [dx, dy, dw, dh, l1x, l1y, ... ]
        
        # cx = cx_grid + dx * stride
        # cy = cy_grid + dy * stride
        # w = exp(dw) * stride
        # h = exp(dh) * stride
        
        bbox = np.zeros_like(loc_v[:, :4])
        bbox[:, 0] = priors_v[:, 0] + loc_v[:, 0] * priors_v[:, 2] # cx
        bbox[:, 1] = priors_v[:, 1] + loc_v[:, 1] * priors_v[:, 3] # cy
        bbox[:, 2] = priors_v[:, 2] * np.exp(loc_v[:, 2])          # w
        bbox[:, 3] = priors_v[:, 3] * np.exp(loc_v[:, 3])          # h
        
        # Convert cx,cy,w,h to x,y,w,h (TopLeft)
        bbox[:, 0] -= bbox[:, 2] / 2
        bbox[:, 1] -= bbox[:, 3] / 2
        
        # Decode Landmarks
        landmarks = np.zeros_like(loc_v[:, 4:])
        for i in range(5):
             # lx = cx_grid + dlx * stride
             # ly = cy_grid + dly * stride
             landmarks[:, 2*i] = priors_v[:, 0] + loc_v[:, 4 + 2*i] * priors_v[:, 2]
             landmarks[:, 2*i+1] = priors_v[:, 1] + loc_v[:, 4 + 2*i+1] * priors_v[:, 3]
             
        # Check bounds? OpenCV clip?
        
        # 5. NMS
        # Prepare for NMS: [x, y, w, h]
        # cv2.dnn.NMSBoxes expects [x, y, w, h]
        
        bboxes = bbox.tolist()
        scores_list = scores_v.tolist()        
        # NMS
        indices = cv2.dnn.NMSBoxes(bboxes, scores_list, self.conf_threshold, self.nms_threshold)
        
        if len(indices) == 0:
            return 1, None
        
        indices = np.array(indices).flatten()
        
        # Build final output [N, 15]
        # Format: x1, y1, w, h, kp1_x, kp1_y, ..., kp5_x, kp5_y, score
        final_faces = []
        
        # CRITICAL: Scale factors to convert from resized (640x640) back to original dimensions
        scale_x = orig_w / target_w
        scale_y = orig_h / target_h
        
        for idx in indices:
            # x1, y1, w, h
            x1, y1, w_box, h_box = bbox[idx]
            score_val = scores_v[idx]
            
            # Scale bbox back to original size
            x1_orig = x1 * scale_x
            y1_orig = y1 * scale_y
            w_orig = w_box * scale_x
            h_orig = h_box * scale_y
            
            # Landmarks (5 keypoints = 10 values)
            kps_resized = landmarks[idx].reshape(5, 2) # shape (5, 2)
            
            # Scale landmarks back to original size
            kps_orig = kps_resized.copy()
            kps_orig[:, 0] *= scale_x  # x coords
            kps_orig[:, 1] *= scale_y  # y coords
            
            # Flatten landmarks
            kps_flat = kps_orig.flatten() # [kp1_x, kp1_y, ..., kp5_x, kp5_y]
            
            # Build row: [x1, y1, w, h, kp1_x, kp1_y, ..., kp5_x, kp5_y, score]
            row = np.concatenate([[x1_orig, y1_orig, w_orig, h_orig], kps_flat, [score_val]])
            final_faces.append(row)
        
        if len(final_faces) == 0:
            return 1, None
        
        final_array = np.array(final_faces, dtype=np.float32)
        
        return 1, final_array
