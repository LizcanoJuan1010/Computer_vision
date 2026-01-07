import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # NATS
    NATS_URL: str = os.getenv("NATS_URL", "nats://localhost:4222")

    # NATS Subject Patterns (Multi-Tenancy Aware)
    # The router subscribes to BOTH legacy and new formats for backward compatibility
    INPUT_SUBJECT: str = "camera.*.frame"  # Legacy format (will be deprecated)
    INPUT_SUBJECT_MULTI_TENANT: str = "org.*.zone.*.camera.*.frame"  # New multi-tenancy format
    
    # Redis
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB: int = 0
    
    # Database
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", 5436))
    DB_USER: str = os.getenv("DB_USER", "user")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "password")
    DB_NAME: str = os.getenv("DB_NAME", "vigias")
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # Cache
    L1_TTL: int = 60  # Seconds
    L1_MAXSIZE: int = 1000 # Max number of camera configs in RAM

    # Performance
    LOG_LEVEL: str = "INFO"

settings = Settings()
