from fastapi import APIRouter
from app.api.routes.general import router as general_router
from app.api.routes.cameras import router as cameras_router
from app.api.routes.cameras_nested import router as cameras_nested_router
from app.api.routes.streaming import router as streaming_router
from app.api.routes.alarms import router as alarms_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.faces import router as faces_router
from app.api.routes.organizations import router as organizations_router
from app.api.routes.zones import router as zones_router

# NEW: Import new routers
from app.api.routes.events import router as events_router
from app.api.routes.faces_multitenancy import router as faces_mt_router
from app.api.routes.camera_management import router as camera_management_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.notification_rules import router as notification_rules_router
from app.api.routes.auth import router as auth_router


main_api_router = APIRouter()

# Include legacy routes
main_api_router.include_router(general_router)

# Multi-tenancy routes (new nested structure)
main_api_router.include_router(organizations_router, prefix="/api/v1/orgs", tags=["Organizations"])
main_api_router.include_router(zones_router, prefix="/api/v1/orgs/{org_slug}/zones", tags=["Zones"])
main_api_router.include_router(cameras_nested_router, prefix="/api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras", tags=["Cameras"])

# NEW: Events/Alarms Multi-tenancy
main_api_router.include_router(events_router, prefix="/api/v1", tags=["Events"])

# NEW: Facial Recognition Multi-tenancy
main_api_router.include_router(faces_mt_router, prefix="/api/v1", tags=["Faces (Multi-tenancy)"])

# NEW: Camera Management (Hybrid Model - Client + Admin endpoints)
main_api_router.include_router(camera_management_router, prefix="/api/v1", tags=["Camera Management"])

# NEW: Notification Rules and Channels
main_api_router.include_router(notification_rules_router, prefix="/api/v1", tags=["Notifications & Alerts"])

# NEW: Authentication
main_api_router.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])

# Monitoring
main_api_router.include_router(metrics_router, tags=["Monitoring"])

# Legacy routes (maintained for backward compatibility)
main_api_router.include_router(cameras_router, prefix="/api/v1/cameras", tags=["Cameras (Legacy)"])
main_api_router.include_router(alarms_router, prefix="/api/v1/alarms", tags=["Alarms (Legacy)"])
main_api_router.include_router(streaming_router, prefix="/api/v1/stream", tags=["Streaming"])
main_api_router.include_router(notifications_router, prefix="/ws", tags=["WebSocket"])
main_api_router.include_router(faces_router, prefix="/api/v1/faces", tags=["Faces (Legacy)"])


