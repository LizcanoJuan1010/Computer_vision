import os
import numpy as np
import paddle
from ..config import config

class ActionModel:
    """
    ST-GCN Action Recognition Wrapper (Paddle Native)
    """
    def __init__(self, model_dir="/app/weights/STGCN"):
        self.model_dir = model_dir
        self.predictor = None
        self.input_handle = None
        self.output_handle = None

    def load(self):
        print(f"🚀 Loading ST-GCN Action Model from {self.model_dir}...", flush=True)
        model_file = os.path.join(self.model_dir, "model.pdmodel")
        params_file = os.path.join(self.model_dir, "model.pdiparams")

        if not os.path.exists(model_file) or not os.path.exists(params_file):
            # Try alternate path structure (inference/weights/action/stgcn -> extraction might vary)
            alt_path = "/app/weights/action"
            if os.path.exists(os.path.join(alt_path, "model.pdmodel")):
                self.model_dir = alt_path
                model_file = os.path.join(self.model_dir, "model.pdmodel")
                params_file = os.path.join(self.model_dir, "model.pdiparams")
            else:
                print(f"❌ ST-GCN model not found at {self.model_dir}", flush=True)
                return

        try:
            config_paddle = paddle.inference.Config(model_file, params_file)
            if config.USE_GPU:
                config_paddle.enable_use_gpu(500, 0)
                config_paddle.switch_ir_optim(True)
                config_paddle.enable_memory_optim()
            else:
                config_paddle.disable_gpu()
                config_paddle.enable_mkldnn()

            self.predictor = paddle.inference.create_predictor(config_paddle)
            self.input_handle = self.predictor.get_input_handle(self.predictor.get_input_names()[0])
            self.output_handle = self.predictor.get_output_handle(self.predictor.get_output_names()[0])
            print("✅ ST-GCN Loaded Successfully!", flush=True)
        except Exception as e:
            print(f"❌ Failed to load ST-GCN: {e}", flush=True)

    def predict(self, skeleton_data):
        """
        Recognize action from skeleton sequence.
        skeleton_data: numpy array of shape [Batch, Channels, Frames, Vertices, Person]
                       Format expected by ST-GCN.
        """
        if self.predictor is None:
            return []

        try:
            self.input_handle.copy_from_cpu(skeleton_data)
            self.predictor.run()
            output = self.output_handle.copy_to_cpu()
            
            # Output is usually class probabilities [Batch, Classes]
            actions = []
            for row in output:
                class_id = np.argmax(row)
                score = row[class_id]
                actions.append((class_id, score))
            return actions
        except Exception as e:
            print(f"❌ Action inference error: {e}", flush=True)
            return []
