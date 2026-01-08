import cv2
import numpy as np
import onnxruntime as ort
import os
from ..config import config
from .base import BaseModel

class FaceResult:
    def __init__(self, bbox, kps, det_score, embedding):
        self.bbox = bbox # [x1, y1, x2, y2]
        self.kps = kps
        self.det_score = det_score
        self.embedding = embedding
        # Compatibility attributes
        self.age = None
        self.gender = None

    def __repr__(self):
        return f"<FaceResult bbox={self.bbox} score={self.det_score:.2f}>"

    def __getitem__(self, key):
        # Allow dict-like access for flexibility
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def to_dict(self):
        return {
            "bbox": self.bbox,
            "kps": self.kps,
            "det_score": self.det_score,
            "embedding": self.embedding,
            "age": self.age,
            "gender": self.gender
        }

    def keys(self):
        return ["bbox", "kps", "det_score", "embedding", "age", "gender"]

    def __setitem__(self, key, value):
        setattr(self, key, value)


class FaceModel(BaseModel):
    def __init__(self):
        self.det_model_path = config.FACE_DET_MODEL_PATH
        self.rec_model_path = config.FACE_REC_MODEL_PATH
        self.detector = None
        self.recognizer = None
        self.input_size = (640, 640) # Standard YuNet input, adaptable

    def load(self):
        print(f"Loading Face Models...")
        print(f"  - Detection (YuNet): {self.det_model_path}")
        print(f"  - Recognition (GhostFaceNetV2): {self.rec_model_path}")

        if not os.path.exists(self.det_model_path):
            print(f"WARNING: Face detection model not found at {self.det_model_path}")
        
        if not os.path.exists(self.rec_model_path):
            print(f"WARNING: Face recognition model not found at {self.rec_model_path}")

        try:
            # 1. Initialize YuNet Detector
            self.detector = cv2.FaceDetectorYN.create(
                model=self.det_model_path,
                config="",
                input_size=self.input_size,
                score_threshold=config.FACE_DET_SCORE_THRESHOLD,
                nms_threshold=config.FACE_DET_NMS_THRESHOLD,
                top_k=config.FACE_DET_TOP_K,
                backend_id=cv2.dnn.DNN_BACKEND_DEFAULT,
                target_id=cv2.dnn.DNN_TARGET_CPU 
            )

            # 2. Initialize GhostFaceNetV2 Recognizer (ONNX Runtime)
            providers = ['CPUExecutionProvider']
            if config.USE_TENSORRT:
                providers.insert(0, 'CUDAExecutionProvider') 

            self.recognizer = ort.InferenceSession(self.rec_model_path, providers=providers)
            
            print("Face models initialized successfully.")

        except Exception as e:
            print(f"Error loading Face models: {e}")
            raise e

    def _preprocess_recognition(self, image, keypoints):
        """
        Aligns and crops the face using standard ArcFace 5-point alignment.
        """
        # Standard 5 landmarks for 112x112
        REFERENCE_PTS = np.array([
            [38.2946, 51.6963],
            [73.5318, 51.5014],
            [56.0252, 71.7366],
            [41.5493, 92.3655],
            [70.7299, 92.2041]
        ], dtype=np.float32)

        dst_pts = REFERENCE_PTS
        src_pts = keypoints.astype(np.float32)
        
        # Estimate affine transform
        tform = cv2.estimateAffinePartial2D(src_pts, dst_pts)[0]
        
        if tform is None:
             # Fallback if alignment fails: just resize? Or return None?
             # Return resized crop of original bbox? 
             # For now, return None to signal failure
             return None

        # Warp
        face_img = cv2.warpAffine(image, tform, (112, 112))
        
        # Normalize for GhostFaceNet: (data - 127.5) / 127.5
        face_img = (face_img.astype(np.float32) - 127.5) / 127.5
        
        # CHW format
        face_img = face_img.transpose(2, 0, 1)
        face_img = np.expand_dims(face_img, axis=0) # Batch dim
        
        return face_img

    def predict(self, frames):
        """
        Detects faces in frames and returns embeddings + bboxes + kps.
        Returns: List of detection results per frame.
                 Each result is a list of FaceResult objects.
        """
        if not self.detector:
            raise Exception("Face Model not loaded")
        
        # Handling single frame vs list
        single_input = False
        if not isinstance(frames, list):
            frames = [frames]
            single_input = True
            
        results = []
        
        input_name = self.recognizer.get_inputs()[0].name 

        for frame in frames:
            frame_res = []
            h, w, _ = frame.shape
            
            # YuNet requires setting input size matching the image (or scale image)
            self.detector.setInputSize((w, h))
            
            # Detect
            _, faces = self.detector.detect(frame)
            
            if faces is not None:
                for face_data in faces:
                    confidence = face_data[14]
                    bbox = face_data[0:4].astype(int) # x, y, w, h
                    
                    # Convert xywh to xyxy
                    x1, y1, w_b, h_b = bbox
                    x2, y2 = x1 + w_b, y1 + h_b
                    
                    # Keypoints
                    landmarks = face_data[4:14].reshape((5, 2))
                    
                    # Alignment & Recognition
                    face_blob = self._preprocess_recognition(frame, landmarks)
                    
                    if face_blob is not None:
                        # Run Inference
                        embedding = self.recognizer.run(None, {input_name: face_blob})[0]
                        # embedding shape (1, 512)
                        
                        # Normalize embedding (L2)
                        embedding = embedding / np.linalg.norm(embedding)
                        
                        res_obj = FaceResult(
                            bbox=np.array([x1, y1, x2, y2]), # Ensure numpy for compatibility
                            kps=landmarks,
                            det_score=confidence,
                            embedding=embedding.flatten()
                        )
                        frame_res.append(res_obj)
            
            results.append(frame_res)

        if single_input:
            return results[0]
        return results
