# PPYOLOE-s Multi-Class Detection Model (Production)

## 1. Model Overview
This model is a fine-tuned version of **PP-YOLOE-s** (Small), trained for **Multi-Class Detection**. It is optimized for real-time inference on GPU and Edge devices.

**Key Characteristics:**
*   **Architecture**: PP-YOLOE-s (Anchor-free, CSPResNet backbone).
*   **Input Resolution**: 640x640 (Fixed shape for ONNX/TRT).
*   **Framework**: PaddlePaddle (Exported from v2.6/3.x).
*   **Precision**: FP32 (Native), FP16 (supported in TensorRT).
*   **Post-processing**:
    *   **NMS**: MultiClassNMS included in the graph.
    *   **Top-K**: 1000 detections.
    *   **Score Threshold**: 0.01 (Configurable).

## 2. Supported Classes
The model detects 3 classes:
| ID | Name | Description |
| :--- | :--- | :--- |
| **0** | **person** | Human detection |
| **1** | **car** | Vehicle detection |
| **2** | **motorcycle** | Motorcycle/Bike detection |

## 3. Evaluation Metrics
*Note: Values based on the best training checkpoint (Global mAP).*

| Metric | Value | Description |
| :--- | :--- | :--- |
| **mAP (0.50:0.95)** | **0.528** | Global Mean Average Precision (All Classes). |
| **mAP (0.50)** | **0.750** | Precision at strict 50% IoU. |
| **AP (Per Class)** | **Aggregated** | Per-class breakdown not available in summary logs. Global mAP represents average performance across all 3 classes. |

**Performance Analysis:**
The model is optimized for the MOT20 dataset (crowded scenarios). The global mAP of 0.528 indicates solid detection performance across the target classes (Person, Car, Motorcycle).

## 4. Directory Structure
```
production_model/
├── inference_model/        # NATIVE PADDLE FORMAT (Best for PPHuman / Python)
│   ├── model.pdmodel       # Network Graph
│   ├── model.pdiparams     # Weights
│   └── infer_cfg.yml       # Preprocessing Config (Normalization, Resize)
├── onnx/                   # ONNX FORMAT (Best for Compatibility)
│   └── model.onnx          # Universal model (Opset 11)
├── paddle26_export/        # Intermediate export used for conversion
├── weights/                # ORIGINAL CHECKPOINTS
│   └── best_model.pdparams # Trainable weights
└── README.md
```

## 5. Usage Instructions

### A. Python (Paddle Inference)
Recommended for highest performance on NVIDIA GPUs.
```python
import cv2
import paddle.inference as paddle_infer

# 1. Config
config = paddle_infer.Config("inference_model/model.pdmodel", "inference_model/model.pdiparams")
config.enable_use_gpu(1000, 0)
config.enable_memory_optim()
predictor = paddle_infer.create_predictor(config)

# 2. Preprocessing (Resize to 640x640, Normalize)
# ... (Use Deploy utils or implement standard normalize)

# 3. Inference
input_names = predictor.get_input_names()
input_handle = predictor.get_input_handle(input_names[0])
input_handle.reshape([1, 3, 640, 640])
# input_handle.copy_from_cpu(img_data)
predictor.run()
```

### B. PPHuman Pipeline
To use this model in the PPHuman tracking system:
1.  Copy `inference_model` to your deployment folder.
2.  Edit your pipeline config (e.g., `infer_cfg_pphuman.yml`):
    ```yaml
    DET:
      model_dir: /abs/path/to/production_model/inference_model
    ```

### C. ONNX Runtime / TensorRT
The `onnx/model.onnx` file is standard Opset 11.
*   **TensorRT Conversion**:
    ```bash
    trtexec --onnx=production_model/onnx/model.onnx --saveEngine=model.trt --fp16
    ```
