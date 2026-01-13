
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
        h, w, _ = img.shape
        
        # 1. Resize/Pad
        # YuNet expects the set input size. We assume img matches self.input_size or we resize?
        # cv2.FaceDetectorYN usually handles resizing internally if input size is set?
        # Actually cv2 impl requires us to resize manually or SetInputSize matches image.
        # Here we assume setInputSize was called with (w, h).
        
        # If setInputSize was called with something else, we might need to verify.
        # For simplicity, let's assume the caller ensures consistency or we check.
        
        if self.input_size != (w, h):
            # Update priors input changed (dynamic reshape support)
            self.setInputSize((w, h))

        if self.priors is None or self._input_h != h or self._input_w != w:
             self._input_h, self._input_w = h, w
             self.priors = self._generate_priors(h, w)

        # 2. Preprocess
        # BGR, HWC -> 1, 3, H, W
        blob = cv2.dnn.blobFromImage(img, 1.0, (w, h), (0, 0, 0), swapRB=False, crop=False)
        
        # 3. Inference
        outputs = self.session.run(self.output_names, {self.input_name: blob})
        
        # outputs usually:
        # [0]: loc  [1, N, 14]  (cx, cy, w, h, 5 landmarks (x,y))
        # [1]: conf [1, N, 2]   (background, face)
        # [2]: iou  [1, N, 1]   (iou score)
        
        # Check shapes
        # Some versions might concat. Let's assume standard 3 headers or 1.
        # If output len is 1, it might be pre-decoded? No, ONNX usually raw.
        # But YuNet ONNX from Zoo usually has 3 outputs.
        
        # Let's handle logical outputs by checking shapes
        # loc: shape[-1] == 14
        # conf: shape[-1] == 2
        # iou: shape[-1] == 1
        
        loc, conf, iou = None, None, None
        for o in outputs:
            if o.shape[-1] == 14: loc = o
            elif o.shape[-1] == 2: conf = o
            elif o.shape[-1] == 1: iou = o
            
        if loc is None or conf is None:
            # Maybe concatenated? 
            if len(outputs) == 1:
                # [1, N, 17]?
                pass
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
        
        # Final post-processing logic from YuNet paper/impl:
        # score = sqrt(cls_score * iou_score) ?? Or just cls?
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
        
        indices = cv2.dnn.NMSBoxes(bboxes, scores_list, self.conf_threshold, self.nms_threshold, top_k=self.top_k)
        
        if len(indices) == 0:
             return 0, None
             
        indices = np.array(indices).flatten()
        
        # Assemble Final Output
        # [x, y, w, h, l1x, l1y, ... l5y, score] (15 dims)
        
        final_faces = []
        for idx in indices:
            row = []
            # Box
            row.extend(bbox[idx])
            # Landmarks
            row.extend(landmarks[idx])
            # Score
            row.append(scores_v[idx])
            
            final_faces.append(row)
            
        final_faces = np.array(final_faces, dtype=np.float32)
        
        return 1, final_faces

