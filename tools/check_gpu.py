import onnxruntime as ort
import os
import sys

print(f"Python Executable: {sys.executable}")
print(f"LD_LIBRARY_PATH: {os.environ.get('LD_LIBRARY_PATH', 'Not Set')}")
print(f"ONNX Runtime Version: {ort.__version__}")
print(f"Available Providers: {ort.get_available_providers()}")

try:
    import torch
    print(f"Torch CUDA Available: {torch.cuda.is_available()}")
    print(f"Torch CUDA Version: {torch.version.cuda}")
    print(f"Torch CuDNN Version: {torch.backends.cudnn.version()}")
except ImportError:
    print("Torch not installed")
