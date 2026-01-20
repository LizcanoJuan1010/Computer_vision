# ==============================================================================
# INFERENCE SERVICE - BLACKWELL ENABLED (Official NVIDIA Container 24.11)
# Base: Paddle 3.0 Beta 2 | CUDA 12.6 | TensorRT 10.6 | cuDNN 9
# ==============================================================================

FROM nvcr.io/nvidia/paddlepaddle:24.11-py3

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV TZ=America/Bogota

# 1. SYSTEM DEPENDENCIES
# The container is minimal, we need libs for OpenCV and Audio
# Ubuntu 24.04 notes: libgl1-mesa-glx is replaced by libgl1
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    unzip \
    libgl1 \
    libsndfile1 \
    libglib2.0-0 \
    libgeos-dev \
    # Clean up immediately to reduce size
    && rm -rf /var/lib/apt/lists/*

# Pre-uninstall conflicting opencv if present in base image
RUN python -m pip uninstall -y opencv-python opencv-contrib-python || true

# 2. PYTHON DEPENDENCIES
# Paddle/TensorRT/CUDA are ALREADY INSTALLED in this image!
# Note: Ubuntu 24.04+ (PEP 668) requires --break-system-packages for system-wide pip installs
# CRITICAL: onnxruntime-gpu >= 1.19 required for CUDA 12.x + cuDNN 9.x compatibility

RUN python -m pip install --no-cache-dir --break-system-packages \
    "numpy<2.0.0" \
    shapely \
    scikit-image \
    imgaug \
    onnx \
    "onnxruntime-gpu>=1.20.0" \
    pyclipper \
    lmdb \
    tqdm \
    rapidfuzz \
    opencv-python-headless \
    nats-py \
    aiohttp \
    prometheus-client \
    psycopg2-binary \
    redis \
    python-multipart \
    supervision \
    av \
    PyYAML \
    scikit-learn \
    pandas \
    scipy

# 3. PADDLE FRAMEWORKS (Source Install)
WORKDIR /app
# PaddleOCR
RUN git clone --depth 1 https://github.com/PaddlePaddle/PaddleOCR.git && \
    cd PaddleOCR && \
    python -m pip install --no-cache-dir --break-system-packages .

# PaddleDetection
RUN git clone --depth 1 -b develop https://github.com/PaddlePaddle/PaddleDetection.git && \
    cd PaddleDetection && \
    python -m pip install --no-cache-dir --break-system-packages -r requirements.txt && \
    python setup.py install

# 4. MODEL DOWNLOADS & EXPORT
# 4. MODEL LOADING
# Models are downloaded externally via 'download_models.sh' to avoid build timeouts
# and are COPY'd into the container below.

WORKDIR /app
# ... (rest of the file handles copy)

# 5. INFERENCE APP
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --break-system-packages -r requirements.txt || true

COPY . /app/inference
# COPY ./weights/ /app/weights/

# Ensure start script is executable
RUN chmod +x /app/inference/start.sh

ENV PYTHONPATH="${PYTHONPATH}:/app:/app/inference"

CMD ["/app/inference/start.sh"]