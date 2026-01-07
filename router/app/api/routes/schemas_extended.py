from pydantic import BaseModel, UUID4, Json
from typing import List, Optional, Any
from datetime import datetime
from uuid import UUID

# --- Cameras ---
class CameraBase(BaseModel):
    name: str
    rtsp_url: str
    location_name: Optional[str] = None
    meta_info: Optional[dict] = {}
    is_active: bool = True

class CameraCreate(CameraBase):
    zone_id: Optional[UUID] = None  # Multi-tenancy: Optional zone assignment

class CameraResponse(CameraBase):
    id: UUID  # Changed from int to UUID
    zone_id: Optional[UUID] = None  # Multi-tenancy: Link to zone
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Organizations ---
class OrganizationBase(BaseModel):
    slug: str
    name: str
    is_managed: bool = False
    config: Optional[dict] = {}
    is_active: bool = True

class OrganizationCreate(OrganizationBase):
    """Schema for creating a new organization"""
    pass

class OrganizationUpdate(BaseModel):
    """Schema for updating organization (all fields optional)"""
    name: Optional[str] = None
    is_managed: Optional[bool] = None
    config: Optional[dict] = None
    is_active: Optional[bool] = None

class OrganizationResponse(OrganizationBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Zones ---
class OrgZoneBase(BaseModel):
    slug: str
    name: str
    location_description: Optional[str] = None
    geo_bounds: Optional[dict] = None
    is_active: bool = True

class OrgZoneCreate(OrgZoneBase):
    """Schema for creating a new zone"""
    pass

class OrgZoneUpdate(BaseModel):
    """Schema for updating zone (all fields optional)"""
    name: Optional[str] = None
    location_description: Optional[str] = None
    geo_bounds: Optional[dict] = None
    is_active: Optional[bool] = None

class OrgZoneResponse(OrgZoneBase):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Faces ---
class FaceBase(BaseModel):
    name: str

class FaceCreate(FaceBase):
    pass

class FaceResponse(FaceBase):
    id: int  # Faces still use SERIAL (Integer) for pgvector compatibility
    created_at: datetime

    class Config:
        from_attributes = True

# --- Events/Alarms ---
class EventBase(BaseModel):
    event_type: str
    track_id: Optional[str] = None
    confidence: Optional[float] = None
    snapshot_path: Optional[str] = None
    video_clip_path: Optional[str] = None
    bbox: Optional[list] = None
    severity: str = 'MEDIUM'
    status: str = 'PENDING'

class EventResponse(EventBase):
    id: UUID  # Changed from int to UUID
    camera_id: Optional[UUID] = None  # Changed from int to UUID
    created_at: datetime
    occurred_at: datetime

    class Config:
        from_attributes = True

# --- Camera AI Configs (Zones) ---
class CameraAIConfigBase(BaseModel):
    event_type: str
    default_severity: str = 'MEDIUM'
    confidence_threshold: float = 0.700
    debounce_seconds: int = 60
    roi_polygon: Optional[List[List[float]]] = None  # [[x1,y1], [x2,y2], ...]
    active_schedule: Optional[dict] = None
    is_active: bool = True

class CameraAIConfigCreate(CameraAIConfigBase):
    """Schema for creating a new zone configuration"""
    pass

class CameraAIConfigUpdate(BaseModel):
    """Schema for updating zone configuration (all fields optional)"""
    event_type: Optional[str] = None
    default_severity: Optional[str] = None
    confidence_threshold: Optional[float] = None
    debounce_seconds: Optional[int] = None
    roi_polygon: Optional[List[List[float]]] = None
    active_schedule: Optional[dict] = None
    is_active: Optional[bool] = None

class CameraAIConfigResponse(CameraAIConfigBase):
    id: UUID
    camera_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# --- Event Actions (for event management) ---
class EventStatusUpdate(BaseModel):
    new_status: str  # ACKNOWLEDGED, RESOLVED, FALSE_POSITIVE
    comment: Optional[str] = None

class EventActionCreate(BaseModel):
    comment: str

class EventActionResponse(BaseModel):
    id: UUID
    event_id: UUID
    user_id: Optional[UUID] = None
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# --- Faces Multi-tenancy ---
class FaceCreateMultitenancy(BaseModel):
    name: str
    category: str = "KNOWN"  # KNOWN, BLACKLIST, UNKNOWN
    meta_info: Optional[dict] = {}

class FaceUpdateMultitenancy(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    meta_info: Optional[dict] = None

class FaceResponseMultitenancy(BaseModel):
    id: int
    name: str
    organization_id: Optional[UUID] = None
    category: str
    meta_info: Optional[dict] = {}
    image_path: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class FaceSearchRequest(BaseModel):
    threshold: float = 0.6

class FaceMatch(BaseModel):
    face_id: int
    name: str
    category: str
    similarity: float
    meta_info: Optional[dict] = {}

class FaceSearchResult(BaseModel):
    status: str
    matches: List[FaceMatch] = []
    query_time_ms: Optional[float] = None

# --- Camera Management (Hybrid Model) ---
class CameraStatusResponse(BaseModel):
    camera_id: str
    camera_name: str
    state: str  # RUNNING, STOPPED, ERROR, MAINTENANCE
    fps: float
    last_frame_time: Optional[datetime] = None
    uptime_seconds: int
    connection_quality: str  # EXCELLENT, GOOD, FAIR, POOR
    error_message: Optional[str] = None

class CameraHealthResponse(BaseModel):
    camera_id: str
    is_healthy: bool
    checks: dict  # {network_reachable, rtsp_stream_active, etc.}
    last_check_time: datetime
    error_message: Optional[str] = None

class CameraMetricsResponse(BaseModel):
    camera_id: str
    period: str
    avg_fps: float
    frame_drops: int
    error_count: int
    uptime_percentage: float
    bandwidth_mbps: float
    latency_ms: float
    data_points: List[dict] = []

class CameraRestartResponse(BaseModel):
    status: str
    camera_id: str
    message: str
    estimated_ready_time: Optional[str] = None

class CameraSnapshotResponse(BaseModel):
    status: str
    camera_id: str
    snapshot_url: Optional[str] = None
    timestamp: Optional[str] = None
    resolution: Optional[str] = None

class CameraTestConnectionResponse(BaseModel):
    camera_id: str
    success: bool
    reachable: bool
    rtsp_responsive: bool
    stream_playable: bool
    latency_ms: Optional[float] = None
    diagnostics: Optional[str] = None

class MaintenanceModeUpdate(BaseModel):
    enabled: bool
    reason: Optional[str] = None
    until: Optional[datetime] = None

class BulkRestartRequest(BaseModel):
    camera_ids: List[UUID]
    stagger_seconds: int = 5

class BulkRestartResponse(BaseModel):
    total: int
    success: int
    failed: int
    results: List[dict]

# --- Notification Channels ---
class NotificationChannelCreate(BaseModel):
    name: str
    channel_type: str  # EMAIL, SMS, WEBHOOK, SLACK, TELEGRAM, WHATSAPP
    config: dict
    is_active: bool = True

class NotificationChannelUpdate(BaseModel):
    name: Optional[str] = None
    channel_type: Optional[str] = None
    config: Optional[dict] = None
    is_active: Optional[bool] = None

class NotificationChannelResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    channel_type: str
    config: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Notification Rules ---
class NotificationRuleCreate(BaseModel):
    channel_id: UUID
    name: str
    description: Optional[str] = None
    event_types: Optional[List[str]] = None
    severities: Optional[List[str]] = None
    camera_ids: Optional[List[str]] = None
    zone_ids: Optional[List[str]] = None
    active_schedule: Optional[dict] = None
    cooldown_minutes: int = 5
    is_active: bool = True

class NotificationRuleUpdate(BaseModel):
    channel_id: Optional[UUID] = None
    name: Optional[str] = None
    description: Optional[str] = None
    event_types: Optional[List[str]] = None
    severities: Optional[List[str]] = None
    camera_ids: Optional[List[str]] = None
    zone_ids: Optional[List[str]] = None
    active_schedule: Optional[dict] = None
    cooldown_minutes: Optional[int] = None
    is_active: Optional[bool] = None

class NotificationRuleResponse(BaseModel):
    id: UUID
    organization_id: UUID
    channel_id: UUID
    name: str
    description: Optional[str] = None
    event_types: Optional[List[str]] = None
    severities: Optional[List[str]] = None
    camera_ids: Optional[List[str]] = None
    zone_ids: Optional[List[str]] = None
    active_schedule: Optional[dict] = None
    cooldown_minutes: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Notification Logs ---
class NotificationLogResponse(BaseModel):
    id: UUID
    rule_id: Optional[UUID] = None  # Can be null for test notifications
    event_id: Optional[UUID] = None
    channel_type: str
    recipient: str
    status: str  # SENT, FAILED, PENDING
    error_message: Optional[str] = None
    sent_at: datetime

    class Config:
        from_attributes = True

# --- Notification Testing ---
class NotificationTestRequest(BaseModel):
    message: Optional[str] = "This is a test notification from VIGIAS-IA"

class NotificationTestResponse(BaseModel):
    success: bool
    channel_id: str
    channel_type: str
    delivery_time_ms: Optional[float] = None
    message: Optional[str] = None
    error_message: Optional[str] = None
