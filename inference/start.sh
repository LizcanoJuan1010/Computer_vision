#!/bin/bash
set -ex

echo "🚀 INFO: Inference Service Startup Script Initiated"

# Install missing dependencies for PaddleOCR (LPR)
echo "🔧 Installing LPR Dependencies..."
pip install shapely pyclipper scikit-image --break-system-packages || true

# Ensure Headless OpenCV (Fixes SIGABRT/Qt crashes)
echo "🔧 Ensuring Headless OpenCV..."
# Remove system package which conflicts with pip, install libgeos for Shapely
apt-get update && apt-get remove -y python3-opencv && apt-get install -y libgeos-dev || true
pip uninstall -y opencv-python opencv-contrib-python || true
pip install opencv-contrib-python-headless --break-system-packages || true

echo "✅ Using RT-DETR ONNX Runtime (No export needed)"

# Fix Supervision Library (Headless OpenCV Compatibility)
echo "🔧 Patching Supervision Library..."
find /usr/local/lib/python3.12/dist-packages/supervision -name "*.py" -exec sed -i 's/cv2.FONT_HERSHEY_SIMPLEX/1/g' {} + || true

echo "🔍 Checking OpenCV State..."
# python -c "import cv2; print(f'OpenCV Ver: {cv2.__version__}'); print(f'File: {cv2.__file__}'); print(f'Has FaceDetectorYN? {hasattr(cv2, 'FaceDetectorYN')}')"
python -c "import cv2; print('CV2 imported successfully')"

echo "🚀 Starting Main Application..."
exec python -m inference.main
