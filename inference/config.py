import os

class Config:
    # NATS
    NATS_URL = os.getenv("NATS_URL", "nats://localhost:4223")
    SUBJECT = os.getenv("NATS_SUBJECT", ">")

    # Database - Conecta a la BD de Vision AI
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5436")  # Puerto expuesto en docker-compose.yml
    DB_USER = os.getenv("DB_USER", "user")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
    DB_NAME = os.getenv("DB_NAME", "vigias")
    
    @property
    def DB_CONN_STR(self):
        return f"dbname={self.DB_NAME} user={self.DB_USER} password={self.DB_PASSWORD} host={self.DB_HOST} port={self.DB_PORT}"

    # ==========================================================================
    # MODEL PATHS - Updated for NGC Container + RT-DETR + PP-OCRv4
    # ==========================================================================
    
    # PP-Human (RT-DETR Detection)
    PPHUMAN_CONFIG_PATH = "inference/config/pphuman.yaml"
    # RT-DETR exported model (downloaded & exported in Dockerfile)
    # Note: export_model puts files in a subdirectory named after the config
    PPHUMAN_DET_MODEL_DIR = "/app/weights/human_det/rtdetr_r18.onnx"
    # Fallback if export failed
    PPHUMAN_DET_MODEL_DIR_ALT = "/app/weights/human_det"
    
    # PP-Human Attributes (PPLCNet)
    PPHUMAN_ATTR_MODEL_DIR = "/app/weights/attributes/PPLCNet_x1_0_person_attribute_945_infer"
    
    # RTMPose for Skeleton/Pose (downloaded in Dockerfile)
    PPHUMAN_POSE_MODEL_DIR = "/app/weights/pose"
    
    # Face Detection (YuNet - downloaded in Dockerfile)
    FACE_DET_MODEL_PATH = os.getenv(
        "FACE_DET_MODEL_PATH", 
        "/app/weights/face/yunet.onnx"
    )
    # Fallback to local weights if container path not found
    FACE_DET_MODEL_PATH_ALT = "/app/weights/face/face_detection_yunet_2023mar.onnx"
    
    # Face Recognition (GhostFaceNetV2)
    FACE_REC_MODEL_PATH = os.getenv(
        "FACE_REC_MODEL_PATH", 
        "/app/weights/face/ghostfacenetv2.onnx"
    )
    
    # OCR Models for LPR (PP-OCRv4 Server - downloaded in Dockerfile)
    OCR_DET_MODEL_DIR = "/app/weights/ocr/det"
    OCR_REC_MODEL_DIR = "/app/weights/ocr/rec"
    OCR_CLS_MODEL_DIR = "/app/weights/ocr/cls"
    
    # Face Detection Config (YuNet)
    FACE_DET_SCORE_THRESHOLD = 0.6
    FACE_DET_NMS_THRESHOLD = 0.3
    FACE_DET_TOP_K = 5000
    
    # Logic
    SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.85"))

    # Scalability (Sharding)
    INSTANCE_ID = int(os.getenv("INSTANCE_ID", "0"))
    TOTAL_INSTANCES = int(os.getenv("TOTAL_INSTANCES", "1"))

    # Optimization
    USE_TENSORRT = os.getenv("USE_TENSORRT", "false").lower() == "true"
    TENSORRT_PRECISION = os.getenv("TENSORRT_PRECISION", "fp16") # fp16, fp32, int8 

    # Defaults
    DEFAULT_DET_CONFIDENCE = 0.5
    DEFAULT_INTRUSION_CLASSES = [0] # Persons
    DEFAULT_INTRUSION_DEBOUNCE = 3.0 
    DEFAULT_LINE_CROSSING_CLASSES = [0, 2, 5, 7] # Person, Car, Bus, Truck

    # LPR
    LPR_MODEL_NAME = "paddleocr_v4"
    DEFAULT_LPR_CONFIDENCE = 0.45

    # Face Cache (LFU Hybrid)
    FACE_CACHE_L1_CAPACITY = int(os.getenv("FACE_CACHE_L1_CAPACITY", "1000"))
    FACE_CACHE_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")
    FACE_CACHE_ENABLED = os.getenv("FACE_CACHE_ENABLED", "true").lower() == "true"
    FACE_CACHE_INCLUDE_GLOBAL_BLACKLIST = True

config = Config()
