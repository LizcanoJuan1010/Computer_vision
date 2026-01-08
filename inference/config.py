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

    # Models
    # PP-Human (PaddlePaddle)
    PPHUMAN_CONFIG_PATH = "inference/config/pphuman.yaml" # Placeholder for config
    PPHUMAN_DET_MODEL_DIR = "/app/weights/mot_ppyoloe_l_36e_pipeline"
    PPHUMAN_ATTR_MODEL_DIR = "/app/weights/PPLCNet_x1_0_person_attribute_945_infer"
    PPHUMAN_ACTION_MODEL_DIR = "/app/weights/STGCN"
    PPHUMAN_SMOKING_MODEL_DIR = "/app/weights/ppyoloe_crn_s_80e_smoking_visdrone"
    PPHUMAN_CALLING_MODEL_DIR = "/app/weights/PPHGNet_tiny_calling_halfbody"
    
    FACE_DET_MODEL_PATH = os.getenv("FACE_DET_MODEL_PATH", "/app/weights/face_detection_yunet_2023mar.onnx")
    FACE_REC_MODEL_PATH = os.getenv("FACE_REC_MODEL_PATH", "/app/weights/ghostfacenetv2.onnx")
    
    # Face Detection Config (YuNet)
    FACE_DET_SCORE_THRESHOLD = 0.6
    FACE_DET_NMS_THRESHOLD = 0.3
    FACE_DET_TOP_K = 5000
    
    # Logic
    SIMILARITY_THRESHOLD = 0.85 

    # Optimization
    USE_TENSORRT = os.getenv("USE_TENSORRT", "true").lower() == "true"
    TENSORRT_PRECISION = os.getenv("TENSORRT_PRECISION", "fp16") # fp16, fp32, int8 

    # Defaults
    DEFAULT_DET_CONFIDENCE = 0.5
    DEFAULT_INTRUSION_CLASSES = [0] # Persons
    DEFAULT_INTRUSION_DEBOUNCE = 3.0 
    DEFAULT_LINE_CROSSING_CLASSES = [0, 2, 5, 7] # Person, Car, Bus, Truck

    # LPR
    LPR_MODEL_NAME = "paddleocr_stub" # Placeholder for future PaddleOCR integration
    DEFAULT_LPR_CONFIDENCE = 0.45

    # Face Cache (LFU Hybrid)
    FACE_CACHE_L1_CAPACITY = int(os.getenv("FACE_CACHE_L1_CAPACITY", "1000"))  # Max faces in L1 memory
    FACE_CACHE_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")
    FACE_CACHE_ENABLED = os.getenv("FACE_CACHE_ENABLED", "true").lower() == "true"
    FACE_CACHE_INCLUDE_GLOBAL_BLACKLIST = True  # Always search global blacklist

config = Config()
