#!/bin/bash
set -ex

echo "🚀 INFO: Inference Service Startup Script Initiated"

# Runtime Dependencies handled in Dockerfile
echo "✅ Operational Environment Ready"

echo "✅ Using RT-DETR ONNX Runtime (No export needed)"

# Fix Supervision Library (Headless OpenCV Compatibility)
echo "🔧 Patching Supervision Library..."
find /usr/local/lib/python3.12/dist-packages/supervision -name "*.py" -exec sed -i 's/cv2.FONT_HERSHEY_SIMPLEX/1/g' {} + || true

echo "🔍 Checking OpenCV State..."
# python -c "import cv2; print(f'OpenCV Ver: {cv2.__version__}'); print(f'File: {cv2.__file__}'); print(f'Has FaceDetectorYN? {hasattr(cv2, 'FaceDetectorYN')}')"
python -c "import cv2; print('CV2 imported successfully')"

echo "🚀 Starting Main Application..."
exec python -m inference.main
