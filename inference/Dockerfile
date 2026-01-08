# Dockerfile para Inference Service (YOLO + InsightFace + LPR)
# Requiere NVIDIA GPU con CUDA 11.8 + CUDNN 8 (PaddlePaddle compatible)

FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Evitar prompts interactivos
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# NVIDIA CUDNN Path Fix
# NVIDIA CUDNN Path Fix - Include pip installed nvidia libs
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib/x86_64-linux-gnu:/usr/local/cuda/lib64:/usr/local/cuda/targets/x86_64-linux/lib/:/usr/local/lib/python3.11/dist-packages/nvidia/cudnn/lib:/usr/local/lib/python3.11/dist-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/dist-packages/nvidia/cuda_runtime/lib

# 2. Configurar entorno y dependencias sistema
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    python3.11-dev \
    wget \
    curl \
    git \
    unzip \
    build-essential \
    libopencv-dev \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libnvinfer8 \
    libnvinfer-plugin8 \
    && rm -rf /var/lib/apt/lists/*

# Configurar Python 3.11 como default (incluyendo python3)
RUN ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/python3.11 /usr/bin/python3

# Install pip for Python 3.11
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11

WORKDIR /app

# Copiar requirements
COPY requirements.txt .

# Skip Torch install - Using ONNX Runtime for Face and Paddle for Human

# Instalar dependencias Python
RUN python -m pip install --no-cache-dir -r requirements.txt

# Configurar LD_LIBRARY_PATH y Symlinks para CUDA/TRT
# Ensure libcudnn.so symlink exists (required by some Paddle ops)
RUN ln -sf /usr/lib/x86_64-linux-gnu/libcudnn.so.8 /usr/lib/x86_64-linux-gnu/libcudnn.so

ENV LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:/usr/lib/x86_64-linux-gnu:/usr/local/lib/python3.11/dist-packages/nvidia/cudnn/lib:/usr/local/lib/python3.11/dist-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/dist-packages/nvidia/cufft/lib:/usr/local/lib/python3.11/dist-packages/nvidia/curand/lib:/usr/local/lib/python3.11/dist-packages/nvidia/cusolver/lib:/usr/local/lib/python3.11/dist-packages/nvidia/cusparse/lib:/usr/local/lib/python3.11/dist-packages/nvidia/nccl/lib:/usr/local/lib/python3.11/dist-packages/nvidia/nvtx/lib"
# Install PaddlePaddle GPU (CUDA 11.2+ compatible usually, check matrix)
# For CUDA 12.x, we might need a specific wheel or use the latest stable.
# Using 2.6.0 which is stable. 
RUN python -m pip install --no-cache-dir paddlepaddle-gpu==2.6.1 -f https://www.paddlepaddle.org.cn/whl/linux/mkl/avx/stable.html

# Install PaddleDetection & PaddleOCR

# Install PaddleOCR & other libs
RUN python -m pip install --no-cache-dir paddleocr==2.7.3 shapely scikit-image imgaug


# Install PaddleDetection (Paddledet) & Dependencies
# We clone the repo to get the deployment pipelines scripts (deploy/pipeline)
# Using release/2.8 branch as identified by user for latest features (2.8.1)
RUN git clone -b release/2.8 https://github.com/PaddlePaddle/PaddleDetection.git /app/PaddleDetection && \
    cd /app/PaddleDetection && \
    python -m pip install -r requirements.txt && \
    python -m pip install -e .

# SYSTEM FIX: Patch infer.py to avoid NameError: FLAGS when imported
# Fixed MockFlags to return empty string instead of None to avoid stat(None) errors
RUN echo "class MockFlags:\n    def __getattr__(self, name): return \"\"\n    def __bool__(self): return False\nFLAGS = MockFlags()" > /tmp/header.py && \
    cat /tmp/header.py /app/PaddleDetection/deploy/python/infer.py > /tmp/infer.py && \
    mv /tmp/infer.py /app/PaddleDetection/deploy/python/infer.py


# Fix OpenCV compatibility (AttributeError: cv2.dnn.DictValue) AND NumPy 2.x incompatibility
# Run AFTER PaddleDetection install to prevent it from upgrading to broken versions
RUN python -m pip uninstall -y opencv-python opencv-contrib-python numpy || true
RUN python -m pip install --no-cache-dir "numpy<2.0.0" "opencv-python-headless==4.8.0.74" --force-reinstall

# Create weights directory (Outside of /app/inference to avoid volume mount override)
WORKDIR /app/weights

# Download PP-Human Models (Inference/Exported format)
# 1. Detection (PP-YOLOE-L)
RUN wget -q https://bj.bcebos.com/v1/paddledet/models/pipeline/mot_ppyoloe_l_36e_pipeline.zip && \
    unzip -q mot_ppyoloe_l_36e_pipeline.zip && \
    rm mot_ppyoloe_l_36e_pipeline.zip

# 2. Attribute (PP-LCNet) - Corrected URL (945_infer)
RUN wget -q https://bj.bcebos.com/v1/paddledet/models/pipeline/PPLCNet_x1_0_person_attribute_945_infer.zip && \
    unzip -q PPLCNet_x1_0_person_attribute_945_infer.zip && \
    rm PPLCNet_x1_0_person_attribute_945_infer.zip

# 3. Action (ST-GCN for Fall/Fight) - Standard STGCN
RUN wget -q https://bj.bcebos.com/v1/paddledet/models/pipeline/STGCN.zip && \
    unzip -q STGCN.zip && \
    rm STGCN.zip

# 4. Use-case: Smoking (Object Detection based)
RUN wget -q https://bj.bcebos.com/v1/paddledet/models/pipeline/ppyoloe_crn_s_80e_smoking_visdrone.zip && \
    unzip -q ppyoloe_crn_s_80e_smoking_visdrone.zip && \
    rm ppyoloe_crn_s_80e_smoking_visdrone.zip

# 5. Use-case: Calling (Classification based)
RUN wget -q https://bj.bcebos.com/v1/paddledet/models/pipeline/PPHGNet_tiny_calling_halfbody.zip && \
    unzip -q PPHGNet_tiny_calling_halfbody.zip && \
    rm PPHGNet_tiny_calling_halfbody.zip && \
    # 6. ReID Model (Person Search)
    wget -q https://bj.bcebos.com/v1/paddledet/models/pipeline/reid_model.zip && \
    unzip -q reid_model.zip && \
    rm reid_model.zip

# 7. Video Action (Fight Detection - TSM)
RUN wget -q https://videotag.bj.bcebos.com/PaddleVideo-release2.3/ppTSM_fight.zip && \
    unzip -q ppTSM_fight.zip && \
    mv ppTSM pptsm_fight_detection && \
    rm ppTSM_fight.zip

# Return to app root
WORKDIR /app

# Add PaddleDetection to PYTHONPATH so we can import 'deploy.pipeline'
ENV PYTHONPATH="${PYTHONPATH}:/app/PaddleDetection:/app/PaddleDetection/deploy/pipeline"

# Copiar código de inference
COPY . .

# Descargar modelos en build time (opcional - comentar si prefieres lazy loading)
# Descargar modelos en build time (opcional - comentar si prefieres lazy loading)
# RUN python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')" - REMOVED for PP-Human

# Exponer puerto de debug stream
EXPOSE 5000

# Variables de entorno
ENV DB_HOST=vision-postgres
ENV DB_PORT=5432
ENV DB_USER=vision_user
ENV DB_PASSWORD=vision_pass
ENV DB_NAME=vigias_vision
ENV NATS_URL=nats://vision-nats:4222
ENV REDIS_URL=redis://vision-redis:6379/0

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Ejecutar inference service
CMD ["python", "-m", "inference.main"]
