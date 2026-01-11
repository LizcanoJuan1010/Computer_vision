#!/bin/bash
set -e

# Define base weights directory relative to this script
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/weights"
mkdir -p "$BASE_DIR"

echo "📂 Model Directory: $BASE_DIR"

# Helper function for downloading
download_file() {
    url="$1"
    dest_dir="$2"
    filename="$3"
    
    mkdir -p "$dest_dir"
    target="$dest_dir/$filename"
    
    if [ -f "$target" ]; then
        echo "✅ Exists: $filename"
    else
        echo "⬇️  Downloading $filename..."
        # Use curl with retry and follow redirects
        curl -L --retry 5 --retry-delay 2 --connect-timeout 30 -o "$target" "$url"
        
        # Extract if tar/zip
        if [[ "$filename" == *.tar ]]; then
            echo "📦 Extracting $filename..."
            tar -xf "$target" -C "$dest_dir" --strip-components=1
            rm "$target"
        elif [[ "$filename" == *.zip ]]; then
            echo "📦 Extracting $filename..."
            unzip -q "$target" -d "$dest_dir"
            # Handle potential nested dirs (specific to RTMPose)
            if [ -d "$dest_dir/rtmpose-s_8xb256-420e_coco-256x192" ]; then
                mv "$dest_dir/rtmpose-s_8xb256-420e_coco-256x192"/* "$dest_dir/"
                rmdir "$dest_dir/rtmpose-s_8xb256-420e_coco-256x192"
            fi
            rm "$target"
        fi
    fi
}

echo "--- Starting Downloads ---"

# 1. RT-DETR (Human Detection)
download_file \
    "https://bj.bcebos.com/v1/paddledet/models/rtdetr_r18vd_dec3_6x_coco.pdparams" \
    "$BASE_DIR/human_det" \
    "model.pdparams"

# 2. OCR - Detection (Server Version - Chinese/English compatible)
download_file \
    "https://paddleocr.bj.bcebos.com/PP-OCRv4/chinese/ch_PP-OCRv4_det_server_infer.tar" \
    "$BASE_DIR/ocr/det" \
    "det.tar"

# 3. OCR - Recognition (ENGLISH Version - Better for LatAm Plates)
download_file \
    "https://paddleocr.bj.bcebos.com/PP-OCRv4/english/en_PP-OCRv4_rec_infer.tar" \
    "$BASE_DIR/ocr/rec" \
    "rec.tar"

# 4. OCR - Classification
download_file \
    "https://paddleocr.bj.bcebos.com/dygraph_v2.0/ch/ch_ppocr_mobile_v2.0_cls_infer.tar" \
    "$BASE_DIR/ocr/cls" \
    "cls.tar"

# 5. Person Attributes (PPLCNet)
download_file \
    "https://bj.bcebos.com/v1/paddledet/models/pipeline/PPLCNet_x1_0_person_attribute_945_infer.tar" \
    "$BASE_DIR/attributes" \
    "attr.tar"

# 6. Face Detection (YuNet)
download_file \
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
    "$BASE_DIR/face" \
    "yunet.onnx"

# 7. Pose Estimation (Action Recognition Skeleton)
# User manually provided 'end2end.onnx' (RTMPose). Skipping download.
# download_file "..." "$BASE_DIR/pose" "pose.zip"

# 8. Action Recognition (Fight Detection - ST-GCN)
download_file \
    "https://bj.bcebos.com/v1/paddledet/models/pipeline/STGCN.zip" \
    "$BASE_DIR/action" \
    "stgcn.zip"

echo "✅ All downloads complete!"
echo "👉 Now run: wsl docker compose build inference --no-cache"
