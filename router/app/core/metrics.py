"""
Prometheus Metrics for VIGIAS-IA Router

Tracks key performance indicators:
- API request counts and latencies
- Event creation rates
- Notification delivery metrics
- Face search performance
- Camera health status
- Database query performance
"""
from prometheus_client import Counter, Histogram, Gauge, Info
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
import time

# ============================================================================
# API METRICS
# ============================================================================

# Request counter
api_requests_total = Counter(
    'vigias_api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status_code']
)

# Request duration histogram
api_request_duration_seconds = Histogram(
    'vigias_api_request_duration_seconds',
    'API request duration in seconds',
    ['method', 'endpoint'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# ============================================================================
# EVENT METRICS
# ============================================================================

# Events created
events_created_total = Counter(
    'vigias_events_created_total',
    'Total events created',
    ['event_type', 'severity']
)

# Events by status
events_by_status = Gauge(
    'vigias_events_by_status',
    'Number of events by status',
    ['status']
)

# Event processing latency
event_processing_duration_seconds = Histogram(
    'vigias_event_processing_duration_seconds',
    'Event processing duration in seconds',
    ['event_type'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# ============================================================================
# NOTIFICATION METRICS
# ============================================================================

# Notifications sent
notifications_sent_total = Counter(
    'vigias_notifications_sent_total',
    'Total notifications sent',
    ['channel_type', 'status']
)

# Notification delivery time
notification_delivery_duration_seconds = Histogram(
    'vigias_notification_delivery_duration_seconds',
    'Notification delivery time in seconds',
    ['channel_type'],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0]
)

# Notification rules evaluated
notification_rules_evaluated_total = Counter(
    'vigias_notification_rules_evaluated_total',
    'Total notification rules evaluated',
    ['result']  # matched, skipped_cooldown, skipped_schedule
)

# ============================================================================
# FACE RECOGNITION METRICS
# ============================================================================

# Face searches
face_searches_total = Counter(
    'vigias_face_searches_total',
    'Total face recognition searches',
    ['result']  # match, no_match, error
)

# Face search duration
face_search_duration_seconds = Histogram(
    'vigias_face_search_duration_seconds',
    'Face recognition search duration in seconds',
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

# Known faces in database
known_faces_count = Gauge(
    'vigias_known_faces_total',
    'Total number of known faces in database',
    ['category']  # KNOWN, BLACKLIST, UNKNOWN
)

# ============================================================================
# CAMERA HEALTH METRICS
# ============================================================================

# Cameras by status
cameras_by_status = Gauge(
    'vigias_cameras_by_status',
    'Number of cameras by status',
    ['status']  # ONLINE, OFFLINE, ERROR, MAINTENANCE
)

# Camera FPS
camera_fps = Gauge(
    'vigias_camera_fps',
    'Current FPS per camera',
    ['camera_id', 'camera_name']
)

# Camera frames dropped
camera_frames_dropped_total = Counter(
    'vigias_camera_frames_dropped_total',
    'Total frames dropped per camera',
    ['camera_id', 'camera_name']
)

# Camera CPU usage
camera_cpu_percent = Gauge(
    'vigias_camera_cpu_percent',
    'CPU usage percentage per camera',
    ['camera_id', 'camera_name']
)

# Camera memory usage
camera_memory_mb = Gauge(
    'vigias_camera_memory_mb',
    'Memory usage in MB per camera',
    ['camera_id', 'camera_name']
)

# ============================================================================
# DATABASE METRICS
# ============================================================================

# Database query duration
db_query_duration_seconds = Histogram(
    'vigias_db_query_duration_seconds',
    'Database query duration in seconds',
    ['operation'],  # select, insert, update, delete
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

# Database connections
db_connections_active = Gauge(
    'vigias_db_connections_active',
    'Number of active database connections'
)

# ============================================================================
# SYSTEM METRICS
# ============================================================================

# Application info
app_info = Info(
    'vigias_app_info',
    'Application information'
)

# Set static app info
app_info.info({
    'version': '2.0',
    'component': 'router',
    'environment': 'production'
})

# NATS connection status
nats_connected = Gauge(
    'vigias_nats_connected',
    'NATS connection status (1=connected, 0=disconnected)'
)

# Redis connection status
redis_connected = Gauge(
    'vigias_redis_connected',
    'Redis connection status (1=connected, 0=disconnected)'
)

# ============================================================================
# METRICS ENDPOINT
# ============================================================================

def get_metrics_response() -> Response:
    """
    Generate Prometheus metrics response.

    Returns:
        FastAPI Response with Prometheus metrics in text format
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def track_request(method: str, endpoint: str, status_code: int, duration: float):
    """Track API request metrics"""
    api_requests_total.labels(method=method, endpoint=endpoint, status_code=status_code).inc()
    api_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)


def track_event_created(event_type: str, severity: str):
    """Track event creation"""
    events_created_total.labels(event_type=event_type, severity=severity).inc()


def track_notification_sent(channel_type: str, status: str, delivery_time_ms: float):
    """Track notification sending"""
    notifications_sent_total.labels(channel_type=channel_type, status=status).inc()
    notification_delivery_duration_seconds.labels(channel_type=channel_type).observe(delivery_time_ms / 1000.0)


def track_face_search(result: str, duration: float):
    """Track face recognition search"""
    face_searches_total.labels(result=result).inc()
    face_search_duration_seconds.observe(duration)


def update_camera_metrics(camera_id: str, camera_name: str, fps: float, cpu: float, memory_mb: int):
    """Update camera health metrics"""
    camera_fps.labels(camera_id=camera_id, camera_name=camera_name).set(fps)
    camera_cpu_percent.labels(camera_id=camera_id, camera_name=camera_name).set(cpu)
    camera_memory_mb.labels(camera_id=camera_id, camera_name=camera_name).set(memory_mb)


def track_db_query(operation: str, duration: float):
    """Track database query performance"""
    db_query_duration_seconds.labels(operation=operation).observe(duration)
