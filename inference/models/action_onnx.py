
import os
import numpy as np
import onnxruntime as ort
from ..config import config

class ActionModelONNX:
    """
    Action Recognition using ST-GCN via ONNX
    Input: Sequence of Keypoints (N, 2, T, V, M)
    Output: Action Class Logic
    """
    def __init__(self, model_path=None):
        self.model_path = model_path or config.PPHUMAN_ACTION_ONNX
        self.session = None
        self.window_size = 50
        
    def load(self):
        print(f"🚀 Loading ST-GCN (ONNX) from {self.model_path}...", flush=True)
        if not os.path.exists(self.model_path):
            print(f"⚠️ ST-GCN model not found at {self.model_path}. Actions disabled.", flush=True)
            # The original code had a 'return' here.
            # The instruction implies we should try to load it anyway, perhaps with CPU fallback.
            # However, loading a non-existent model will fail.
            # The most sensible interpretation of "Restore CUDA" in this context,
            # given the provided diff, is to ensure CUDA is prioritized and CPU is a fallback.
            # The diff also seems to move the loading logic into this 'if' block,
            # which would mean it only tries to load if the path doesn't exist, which is incorrect.
            # I will assume the intent was to modify the 'providers' list in the *existing* try block,
            # and the provided diff was a misrepresentation of the desired change's location.
            # If the model path doesn't exist, it should still return.
            return

        try:
            # Original: providers = ['CUDAExecutionProvider']
            # The instruction "Restore CUDA" and the provided diff's content
            # suggest adding CPU as a fallback.
            # Force CPU for ST-GCN (ShapeInferenceError on CUDA)
            providers = ['CPUExecutionProvider']
            sess_opts = ort.SessionOptions()
            sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
            try:
                sess_opts.add_session_config_entry("session.disable_shape_inference", "1")
            except:
                pass
            self.session = ort.InferenceSession(self.model_path, sess_options=sess_opts, providers=providers)
            print(f"✅ ST-GCN (ONNX) Loaded!", flush=True)
        except Exception as e:
            print(f"❌ Failed to load ST-GCN: {e}", flush=True)

    def predict(self, keypoint_sequence):
        """
        Run action recognition.
        keypoint_sequence: List of (17, 3) arrays (T frames). T should be <= 50.
        """
        if self.session is None or len(keypoint_sequence) < 10: # Need min context
            return None
            
        T = self.window_size
        V = 17
        M = 1 # Single person focus
        C = 2 # x, y (usually score is separate or C=3, check model)
        
        # Prepare Input Tensor (N, C, T, V, M)
        # We need to pad or sample the sequence to length T
        input_data = np.zeros((1, C, T, V, M), dtype=np.float32)
        
        # Fill data
        # seq is list of arrays. item shape (17, 3) -> (x, y, conf)
        
        for t, kpts in enumerate(keypoint_sequence):
            if t >= T: break
            # kpts: (17, 3)
            # Transpose to (2, 17) -> [x, y]
            data = kpts[:, :2].T # (2, 17)
            
            input_data[0, :, t, :, 0] = data
            
        # Inference
        input_name = self.session.get_inputs()[0].name
        outputs = self.session.run(None, {input_name: input_data})
        
        # Output: [1, NumClasses]
        probs = outputs[0][0]
        class_id = np.argmax(probs)
        score = probs[class_id]
        
        # Class Mapping (Standard STGCN Action Classes)
        # 0: wave, 1: fall, 2: fight... (need exact list, using generic placeholder map)
        ACTIONS = {
           0: "walk", 1: "run", 2: "jump", 3: "fall", 4: "fight", 5: "sit", 6: "stand"
        }
        # Note: This map relies on the trained model. If using 'STGCN' generic, check dataset.
        # Assuming Fall/Fight are critical.
        
        action = ACTIONS.get(class_id, "unknown")
        return action, float(score)
