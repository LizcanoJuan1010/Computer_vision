import asyncio
import logging
from contextlib import asynccontextmanager

import uvloop
import nats
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.services.cache import router_cache
from app.services.dispatcher import Dispatcher
from app.api.routes import router as api_router

# 1. Activate uvloop for maximum performance
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Logging setup
logging.basicConfig(level=settings.LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("router.main")

# Global NATS connection
nc = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting AI Router...")
    
    # 0. Verify and Fix Schema (Self-Healing)
    from app.core.schema_init import verify_and_fix_schema
    await verify_and_fix_schema()
    
    await router_cache.connect()
    
    # Connect to NATS
    # Connect to NATS with Retry Logic
    global nc
    MAX_RETRIES = 10
    RETRY_INTERVAL = 2
    
    for attempt in range(MAX_RETRIES):
        try:
            nc = await nats.connect(settings.NATS_URL)
            logger.info(f"Connected to NATS at {settings.NATS_URL}")
            break
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                logger.error(f"Failed to connect to NATS after {MAX_RETRIES} attempts: {e}")
                raise e
            logger.warning(f"NATS connection failed (attempt {attempt+1}/{MAX_RETRIES}). Retrying in {RETRY_INTERVAL}s... Error: {e}")
            await asyncio.sleep(RETRY_INTERVAL)
    
    # Initialize Dispatcher
    dispatcher = Dispatcher(nc)
    
    # Initialize WebSocket Manager
    from app.services.notification import manager
    await manager.start_nats_listener(nc)

    # Initialize Event Handler for automatic notification rules
    from app.services.event_handler import EventHandler, set_event_handler
    event_handler = EventHandler(nc)
    await event_handler.start_listening()
    set_event_handler(event_handler)
    logger.info("Event Handler initialized - automatic notifications enabled")

    # Subscribe to Camera Frames (Both Legacy and Multi-Tenant Formats)
    # Queue Group "router_workers" ensures load balancing if we run multiple replicas

    # Legacy format: camera.*.frame
    await nc.subscribe(settings.INPUT_SUBJECT, queue="router_workers", cb=dispatcher.process_frame)
    logger.info(f"Subscribed to LEGACY subject: {settings.INPUT_SUBJECT}")

    # Multi-tenant format: org.*.zone.*.camera.*.frame
    await nc.subscribe(settings.INPUT_SUBJECT_MULTI_TENANT, queue="router_workers", cb=dispatcher.process_frame)
    logger.info(f"Subscribed to MULTI-TENANT subject: {settings.INPUT_SUBJECT_MULTI_TENANT}")
    
    # Inject NATS status into app state if needed for health checks
    app.state.nc = nc

    yield
    
    # Shutdown
    logger.info("Shutting down...")
    if nc:
        await nc.close()
    await router_cache.close()
    
    from app.core.database import engine
    await engine.dispose()

app = FastAPI(lifespan=lifespan, title="VIGIAS-IA Router")

# Prometheus Middleware - Track all requests
from app.middleware.prometheus import PrometheusMiddleware
app.add_middleware(PrometheusMiddleware)

# CORS Middleware - Allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",  # Angular dev
        "http://localhost:3000",  # Alternative frontend
        "http://127.0.0.1:4200",
        "*",  # Allow all for development (remove in production)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routes
app.include_router(api_router)

if __name__ == "__main__":
    # For local debugging
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

