"""
Camera Management Hybrid Model API endpoints

CLIENT ENDPOINTS (Safe operations - multi-tenancy):
  - GET  /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/status
  - GET  /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/health
  - GET  /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/metrics
  - POST /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/restart
  - POST /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/snapshot
  - POST /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/test-connection

ADMIN ENDPOINTS (Critical operations - provider only):
  - POST   /api/v1/admin/cameras/{camera_id}/start
  - POST   /api/v1/admin/cameras/{camera_id}/stop
  - PUT    /api/v1/admin/cameras/{camera_id}/maintenance-mode
  - POST   /api/v1/admin/cameras/bulk-restart
  - DELETE /api/v1/admin/cameras/{camera_id}/force-disconnect
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import sqlalchemy
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
import json
import logging
import asyncio

from app.core.database import get_db
from app.models import Camera, OrgZone
from app.api.routes.schemas_extended import (
    CameraStatusResponse,
    CameraHealthResponse,
    CameraMetricsResponse,
    CameraRestartResponse,
    CameraSnapshotResponse,
    CameraTestConnectionResponse,
    MaintenanceModeUpdate,
    BulkRestartRequest,
    BulkRestartResponse
)
from app.api.dependencies import get_camera_in_zone

router = APIRouter()
logger = logging.getLogger("router.camera_management")

# Rate limiting storage (in-memory for now - should use Redis in production)
restart_attempts = {}
RESTART_RATE_LIMIT = 3  # Max restarts per camera
RESTART_WINDOW = 300  # 5 minutes in seconds


# ============================================================================
# CLIENT ENDPOINTS (Multi-tenancy - Safe Operations)
# ============================================================================

@router.get("/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/status", response_model=CameraStatusResponse)
async def get_camera_status(
    camera: Camera = Depends(get_camera_in_zone),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Get real-time status of a camera.

    Returns:
    - **state**: RUNNING, STOPPED, ERROR, MAINTENANCE
    - **fps**: Current frames per second
    - **last_frame_time**: Timestamp of last received frame
    - **uptime_seconds**: How long camera has been running
    - **connection_quality**: EXCELLENT, GOOD, FAIR, POOR
    """
    # Query NATS or Redis for real-time camera status
    # For now, return mock data structure
    nc = request.app.state.nc if request else None

    try:
        if nc:
            # Request status from ingest service
            response = await nc.request(
                f"commands.camera.{camera.id}.status",
                b"",
                timeout=2.0
            )
            status_data = json.loads(response.data.decode())
            return status_data
        else:
            # Fallback: Return basic status from database
            return {
                "camera_id": str(camera.id),
                "camera_name": camera.name,
                "state": "UNKNOWN",
                "fps": 0.0,
                "last_frame_time": None,
                "uptime_seconds": 0,
                "connection_quality": "UNKNOWN",
                "error_message": "Status service unavailable"
            }

    except asyncio.TimeoutError:
        return {
            "camera_id": str(camera.id),
            "camera_name": camera.name,
            "state": "ERROR",
            "fps": 0.0,
            "last_frame_time": None,
            "uptime_seconds": 0,
            "connection_quality": "POOR",
            "error_message": "Camera not responding"
        }
    except Exception as e:
        logger.error(f"Status check error for camera {camera.id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/health", response_model=CameraHealthResponse)
async def get_camera_health(
    camera: Camera = Depends(get_camera_in_zone),
    request: Request = None
):
    """
    Get health check information for a camera.

    Returns:
    - **is_healthy**: Overall health status (boolean)
    - **checks**: Individual health check results
      - network_reachable
      - rtsp_stream_active
      - frames_being_processed
      - disk_space_available
    - **last_check_time**: When this health check was performed
    """
    nc = request.app.state.nc if request else None

    try:
        if nc:
            response = await nc.request(
                f"commands.camera.{camera.id}.health",
                b"",
                timeout=3.0
            )
            health_data = json.loads(response.data.decode())
            return health_data
        else:
            return {
                "camera_id": str(camera.id),
                "is_healthy": False,
                "checks": {
                    "network_reachable": False,
                    "rtsp_stream_active": False,
                    "frames_being_processed": False,
                    "disk_space_available": True
                },
                "last_check_time": datetime.utcnow(),
                "error_message": "Health service unavailable"
            }

    except asyncio.TimeoutError:
        return {
            "camera_id": str(camera.id),
            "is_healthy": False,
            "checks": {
                "network_reachable": False,
                "rtsp_stream_active": False,
                "frames_being_processed": False,
                "disk_space_available": True
            },
            "last_check_time": datetime.utcnow(),
            "error_message": "Camera health check timed out"
        }


@router.get("/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/metrics", response_model=CameraMetricsResponse)
async def get_camera_metrics(
    camera: Camera = Depends(get_camera_in_zone),
    request: Request = None,
    period: str = "1h"  # 1h, 24h, 7d
):
    """
    Get performance metrics for a camera over a time period.

    Returns:
    - **avg_fps**: Average frames per second
    - **frame_drops**: Number of dropped frames
    - **error_count**: Number of errors/reconnections
    - **uptime_percentage**: Uptime % for the period
    - **bandwidth_mbps**: Average bandwidth usage
    - **latency_ms**: Average processing latency
    """
    # This would query a time-series database (InfluxDB, Prometheus, etc.)
    # For now, return mock structure
    return {
        "camera_id": str(camera.id),
        "period": period,
        "avg_fps": 15.0,
        "frame_drops": 42,
        "error_count": 2,
        "uptime_percentage": 98.5,
        "bandwidth_mbps": 2.3,
        "latency_ms": 45.2,
        "data_points": []
    }


@router.post("/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/restart", response_model=CameraRestartResponse)
async def restart_camera(
    camera: Camera = Depends(get_camera_in_zone),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Restart a camera (client operation).

    Rate limited to prevent abuse:
    - Max 3 restarts per 5 minutes per camera
    - 30 second cooldown between restarts

    Process:
    1. Validates rate limits
    2. Sends restart command to ingest service
    3. Waits for confirmation
    4. Returns new status
    """
    camera_id_str = str(camera.id)

    # Check maintenance mode
    if camera.meta_info and camera.meta_info.get("maintenance_mode"):
        raise HTTPException(
            status_code=409,
            detail="Camera is in maintenance mode. Contact support to restart."
        )

    # Rate limiting check
    now = datetime.utcnow()
    if camera_id_str in restart_attempts:
        attempts = restart_attempts[camera_id_str]
        # Remove old attempts outside the window
        attempts = [t for t in attempts if (now - t).total_seconds() < RESTART_WINDOW]
        restart_attempts[camera_id_str] = attempts

        if len(attempts) >= RESTART_RATE_LIMIT:
            oldest = min(attempts)
            wait_seconds = RESTART_WINDOW - (now - oldest).total_seconds()
            raise HTTPException(
                status_code=429,
                detail=f"Too many restart attempts. Wait {int(wait_seconds)} seconds."
            )

        # Check cooldown (30 seconds since last restart)
        if attempts and (now - max(attempts)).total_seconds() < 30:
            wait = 30 - (now - max(attempts)).total_seconds()
            raise HTTPException(
                status_code=429,
                detail=f"Cooldown active. Wait {int(wait)} seconds before restarting again."
            )
    else:
        restart_attempts[camera_id_str] = []

    # Send restart command via NATS
    nc = request.app.state.nc if request else None
    if not nc:
        raise HTTPException(status_code=503, detail="NATS unavailable")

    try:
        response = await nc.request(
            f"commands.camera.{camera.id}.restart",
            b"",
            timeout=10.0
        )
        result = json.loads(response.data.decode())

        # Record this restart attempt
        restart_attempts[camera_id_str].append(now)

        # TODO: Audit log this action
        # await audit_log.create(user_id, action="camera.restart", camera_id=camera.id)

        return {
            "status": "success",
            "camera_id": str(camera.id),
            "message": "Camera restart initiated",
            "estimated_ready_time": (now + timedelta(seconds=30)).isoformat()
        }

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Restart command timed out. Camera may not be responding."
        )
    except Exception as e:
        logger.error(f"Restart error for camera {camera.id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/snapshot", response_model=CameraSnapshotResponse)
async def capture_manual_snapshot(
    camera: Camera = Depends(get_camera_in_zone),
    request: Request = None
):
    """
    Capture a manual snapshot from the camera.

    Returns:
    - **snapshot_url**: URL to download the captured image
    - **timestamp**: When the snapshot was taken
    - **resolution**: Image resolution
    """
    nc = request.app.state.nc if request else None
    if not nc:
        raise HTTPException(status_code=503, detail="NATS unavailable")

    try:
        response = await nc.request(
            f"commands.camera.{camera.id}.snapshot",
            b"",
            timeout=5.0
        )
        snapshot_data = json.loads(response.data.decode())

        return {
            "status": "success",
            "camera_id": str(camera.id),
            "snapshot_url": snapshot_data.get("url"),
            "timestamp": snapshot_data.get("timestamp"),
            "resolution": snapshot_data.get("resolution", "640x360")
        }

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Snapshot request timed out")
    except Exception as e:
        logger.error(f"Snapshot error for camera {camera.id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/test-connection", response_model=CameraTestConnectionResponse)
async def test_camera_connection(
    camera: Camera = Depends(get_camera_in_zone),
    request: Request = None
):
    """
    Test RTSP connection to the camera without starting capture.

    Useful for diagnosing connection issues.

    Returns:
    - **reachable**: Can ping the camera IP
    - **rtsp_responsive**: RTSP port is open
    - **stream_playable**: Can decode at least one frame
    - **latency_ms**: Connection latency
    - **diagnostics**: Detailed error messages if any
    """
    nc = request.app.state.nc if request else None
    if not nc:
        raise HTTPException(status_code=503, detail="NATS unavailable")

    try:
        response = await nc.request(
            f"commands.camera.{camera.id}.test",
            json.dumps({"rtsp_url": camera.rtsp_url}).encode(),
            timeout=15.0
        )
        test_results = json.loads(response.data.decode())

        return test_results

    except asyncio.TimeoutError:
        return {
            "camera_id": str(camera.id),
            "success": False,
            "reachable": False,
            "rtsp_responsive": False,
            "stream_playable": False,
            "latency_ms": None,
            "diagnostics": "Connection test timed out (15 seconds)"
        }
    except Exception as e:
        logger.error(f"Connection test error for camera {camera.id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ADMIN ENDPOINTS (Provider Only - Critical Operations)
# ============================================================================

@router.post("/admin/cameras/{camera_id}/start")
async def admin_start_camera(
    camera_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
    # TODO: Add admin auth: current_user: User = Depends(require_admin)
):
    """
    Start camera capture (ADMIN ONLY).

    This is a critical operation that:
    1. Allocates system resources
    2. Starts RTSP capture in ingest service
    3. Begins frame processing pipeline

    Requires: PROVIDER_ADMIN role
    """
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    nc = request.app.state.nc
    if not nc:
        raise HTTPException(status_code=503, detail="NATS unavailable")

    try:
        response = await nc.request(
            f"commands.camera.{camera_id}.start",
            json.dumps({"rtsp_url": camera.rtsp_url}).encode(),
            timeout=10.0
        )
        result = json.loads(response.data.decode())

        # TODO: Audit log
        # await audit_log.create(user_id, action="camera.start", camera_id=camera_id)

        return {
            "status": "success",
            "camera_id": str(camera_id),
            "message": "Camera started successfully"
        }

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Start command timed out")
    except Exception as e:
        logger.error(f"Start error for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/cameras/{camera_id}/stop")
async def admin_stop_camera(
    camera_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
    # TODO: Add admin auth
):
    """
    Stop camera capture (ADMIN ONLY).

    This will:
    1. Stop frame ingestion
    2. Release system resources
    3. Close RTSP connection

    Requires: PROVIDER_ADMIN role
    """
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    nc = request.app.state.nc
    if not nc:
        raise HTTPException(status_code=503, detail="NATS unavailable")

    try:
        response = await nc.request(
            f"commands.camera.{camera_id}.stop",
            b"",
            timeout=10.0
        )
        result = json.loads(response.data.decode())

        # TODO: Audit log

        return {
            "status": "success",
            "camera_id": str(camera_id),
            "message": "Camera stopped successfully"
        }

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Stop command timed out")
    except Exception as e:
        logger.error(f"Stop error for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/cameras/{camera_id}/maintenance-mode")
async def set_maintenance_mode(
    camera_id: UUID,
    maintenance_update: MaintenanceModeUpdate,
    db: AsyncSession = Depends(get_db)
    # TODO: Add admin auth
):
    """
    Enable/disable maintenance mode for a camera (ADMIN ONLY).

    When in maintenance mode:
    - Clients cannot restart the camera
    - Alerts are suppressed (optional)
    - Camera status shows MAINTENANCE

    Useful for:
    - Scheduled maintenance windows
    - Troubleshooting
    - Preventing client interference

    Requires: PROVIDER_ADMIN role
    """
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    # Update meta_info
    if not camera.meta_info:
        camera.meta_info = {}

    camera.meta_info["maintenance_mode"] = maintenance_update.enabled
    camera.meta_info["maintenance_reason"] = maintenance_update.reason
    camera.meta_info["maintenance_until"] = maintenance_update.until.isoformat() if maintenance_update.until else None

    try:
        await db.commit()
        await db.refresh(camera)

        # TODO: Audit log

        return {
            "status": "success",
            "camera_id": str(camera_id),
            "maintenance_mode": maintenance_update.enabled,
            "reason": maintenance_update.reason
        }

    except Exception as e:
        await db.rollback()
        logger.error(f"Maintenance mode error for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/cameras/bulk-restart", response_model=BulkRestartResponse)
async def bulk_restart_cameras(
    bulk_request: BulkRestartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
    # TODO: Add admin auth
):
    """
    Restart multiple cameras at once (ADMIN ONLY).

    Useful for:
    - System-wide updates
    - Mass configuration changes
    - Recovery from network issues

    Parameters:
    - **camera_ids**: List of camera UUIDs to restart
    - **stagger_seconds**: Delay between restarts (default 5s to avoid overload)

    Returns:
    - Success/failure status for each camera

    Requires: PROVIDER_ADMIN role
    """
    nc = request.app.state.nc
    if not nc:
        raise HTTPException(status_code=503, detail="NATS unavailable")

    results = []

    for camera_id in bulk_request.camera_ids:
        camera = await db.get(Camera, camera_id)
        if not camera:
            results.append({
                "camera_id": str(camera_id),
                "status": "error",
                "message": "Camera not found"
            })
            continue

        try:
            response = await nc.request(
                f"commands.camera.{camera_id}.restart",
                b"",
                timeout=10.0
            )
            results.append({
                "camera_id": str(camera_id),
                "status": "success",
                "message": "Restart initiated"
            })

            # Stagger restarts
            if bulk_request.stagger_seconds > 0:
                await asyncio.sleep(bulk_request.stagger_seconds)

        except asyncio.TimeoutError:
            results.append({
                "camera_id": str(camera_id),
                "status": "error",
                "message": "Timeout"
            })
        except Exception as e:
            results.append({
                "camera_id": str(camera_id),
                "status": "error",
                "message": str(e)
            })

    success_count = sum(1 for r in results if r["status"] == "success")
    failure_count = len(results) - success_count

    return {
        "total": len(results),
        "success": success_count,
        "failed": failure_count,
        "results": results
    }


@router.put("/admin/cameras/{camera_id}/status")
async def update_camera_status(
    camera_id: UUID,
    status: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
    # TODO: Add admin auth
):
    """
    Manually update camera status (ADMIN ONLY).

    Allows direct status updates for:
    - **ONLINE**: Camera is actively streaming
    - **OFFLINE**: Camera is disconnected
    - **ERROR**: Camera encountered an error
    - **MAINTENANCE**: Camera is under maintenance

    This endpoint directly updates the database status field.
    Use maintenance-mode endpoint for full maintenance workflow.

    Requires: PROVIDER_ADMIN role
    """
    # Validate status
    valid_statuses = ["ONLINE", "OFFLINE", "ERROR", "MAINTENANCE"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )

    # Get camera
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    try:
        # Update status using raw SQL since we have a custom enum type
        await db.execute(
            sqlalchemy.text("UPDATE cameras SET status = :status WHERE id = :camera_id"),
            {"status": status, "camera_id": str(camera_id)}
        )
        await db.commit()

        logger.info(f"Camera {camera_id} status manually updated to {status}")

        return {
            "status": "success",
            "camera_id": str(camera_id),
            "new_status": status,
            "message": f"Camera status updated to {status}"
        }

    except Exception as e:
        await db.rollback()
        logger.error(f"Status update error for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/cameras/{camera_id}/hot-reload")
async def hot_reload_camera(
    camera_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
    # TODO: Add admin auth
):
    """
    Hot-reload a camera without restarting ingest service (ADMIN ONLY).

    This is the preferred way to add new cameras or reload configuration:
    - Sends NATS command to ingest service
    - Camera starts immediately
    - No service restart required
    - Preserves other running cameras

    Use cases:
    - Adding a new camera from frontend
    - Reloading camera configuration changes
    - Recovering from errors without full restart

    Requires: PROVIDER_ADMIN role
    """
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    nc = request.app.state.nc
    if not nc:
        raise HTTPException(status_code=503, detail="NATS unavailable")

    try:
        # Send reload command via NATS
        response = await nc.request(
            f"commands.camera.{camera_id}.reload",
            json.dumps({"camera_id": str(camera_id)}).encode(),
            timeout=10.0
        )
        result = json.loads(response.data.decode())

        logger.info(f"Camera {camera_id} hot-reloaded successfully")

        return {
            "status": "success",
            "camera_id": str(camera_id),
            "camera_name": camera.name,
            "message": "Camera reloaded successfully",
            "ingest_response": result
        }

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Hot-reload command timed out. Ingest service may not be responding."
        )
    except Exception as e:
        logger.error(f"Hot-reload error for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/admin/cameras/{camera_id}/force-disconnect")
async def force_disconnect_camera(
    camera_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
    # TODO: Add admin auth
):
    """
    Force disconnect a camera (ADMIN ONLY - DANGER).

    This is an emergency operation that:
    - Immediately kills the RTSP connection
    - Does NOT gracefully stop
    - May cause data loss

    Use only when:
    - Camera is completely frozen
    - Normal stop/restart failed
    - Emergency intervention required

    Requires: PROVIDER_ADMIN role + confirmation
    """
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    nc = request.app.state.nc
    if not nc:
        raise HTTPException(status_code=503, detail="NATS unavailable")

    try:
        await nc.publish(
            f"commands.camera.{camera_id}.force_kill",
            b""
        )

        # TODO: Critical audit log
        logger.warning(f"FORCE DISCONNECT executed for camera {camera_id}")

        return {
            "status": "success",
            "camera_id": str(camera_id),
            "message": "Force disconnect command sent",
            "warning": "This is a destructive operation. Camera may need manual restart."
        }

    except Exception as e:
        logger.error(f"Force disconnect error for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
