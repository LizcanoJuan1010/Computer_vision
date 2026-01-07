from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.models import Camera, CameraAIConfig
from app.api.routes.schemas_extended import (
    CameraCreate,
    CameraResponse,
    CameraAIConfigCreate,
    CameraAIConfigUpdate,
    CameraAIConfigResponse
)

router = APIRouter()

@router.get("/", response_model=List[CameraResponse])
async def get_cameras(response: Response, db: AsyncSession = Depends(get_db)):
    """
    DEPRECATED: Use /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/ instead.
    This legacy endpoint will be removed in v2.0.0.
    """
    response.headers["X-Deprecated"] = "true"
    response.headers["X-Sunset"] = "2026-06-01"
    response.headers["Link"] = '</api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/>; rel="alternate"'
    result = await db.execute(select(Camera))
    return result.scalars().all()

@router.post("/", response_model=CameraResponse)
async def create_camera(response: Response, cam: CameraCreate, db: AsyncSession = Depends(get_db)):
    """
    DEPRECATED: Use POST /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/ instead.
    This legacy endpoint will be removed in v2.0.0.
    """
    response.headers["X-Deprecated"] = "true"
    response.headers["X-Sunset"] = "2026-06-01"
    response.headers["Link"] = '</api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/>; rel="alternate"'
    # TODO: Sync with NATS/Redis
    new_cam = Camera(**cam.dict())
    db.add(new_cam)
    await db.commit()
    await db.refresh(new_cam)
    return new_cam

# --- Zone Management Endpoints ---

@router.get("/{camera_id}/zones", response_model=List[CameraAIConfigResponse])
async def get_camera_zones(camera_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Get all zone configurations for a specific camera.

    - **camera_id**: UUID of the camera
    - Returns: List of zone configurations with ROI polygons, event types, and settings
    """
    # Verify camera exists
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    # Get all zones for this camera
    result = await db.execute(
        select(CameraAIConfig).where(CameraAIConfig.camera_id == camera_id)
    )
    return result.scalars().all()

@router.post("/{camera_id}/zones", response_model=CameraAIConfigResponse, status_code=201)
async def create_camera_zone(
    camera_id: UUID,
    zone: CameraAIConfigCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new zone configuration for a camera.

    - **camera_id**: UUID of the camera
    - **event_type**: Type of event to detect (intrusion, loitering, etc.)
    - **roi_polygon**: List of [x, y] coordinates defining the region of interest
    - **confidence_threshold**: Minimum confidence (0.0-1.0) to trigger event
    - **debounce_seconds**: Minimum time between consecutive events
    - **default_severity**: CRITICAL, HIGH, MEDIUM, LOW, INFO

    Note: Only one zone per camera per event_type (enforced by DB constraint)
    """
    # Verify camera exists
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    # Validate event_type
    valid_event_types = ['intrusion', 'loitering', 'line_crossing', 'abandoned_object', 'crowd_detection']
    if zone.event_type not in valid_event_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type. Must be one of: {', '.join(valid_event_types)}"
        )

    # Validate severity
    valid_severities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
    if zone.default_severity not in valid_severities:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid severity. Must be one of: {', '.join(valid_severities)}"
        )

    # Validate ROI polygon if provided
    if zone.roi_polygon:
        if len(zone.roi_polygon) < 3:
            raise HTTPException(
                status_code=400,
                detail="ROI polygon must have at least 3 points"
            )
        for point in zone.roi_polygon:
            if len(point) != 2:
                raise HTTPException(
                    status_code=400,
                    detail="Each polygon point must be [x, y] coordinates"
                )
            if not (0 <= point[0] <= 1 and 0 <= point[1] <= 1):
                raise HTTPException(
                    status_code=400,
                    detail="Polygon coordinates must be normalized (0.0-1.0)"
                )

    # Validate confidence threshold
    if not (0.0 <= zone.confidence_threshold <= 1.0):
        raise HTTPException(
            status_code=400,
            detail="confidence_threshold must be between 0.0 and 1.0"
        )

    # Create new zone
    try:
        new_zone = CameraAIConfig(
            camera_id=camera_id,
            **zone.dict()
        )
        db.add(new_zone)
        await db.commit()
        await db.refresh(new_zone)
        return new_zone
    except Exception as e:
        await db.rollback()
        if "unique_camera_event_config" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"Zone for event_type '{zone.event_type}' already exists for this camera"
            )
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.put("/{camera_id}/zones/{zone_id}", response_model=CameraAIConfigResponse)
async def update_camera_zone(
    camera_id: UUID,
    zone_id: UUID,
    zone_update: CameraAIConfigUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update an existing zone configuration.

    - **camera_id**: UUID of the camera
    - **zone_id**: UUID of the zone configuration to update
    - All fields are optional - only provided fields will be updated
    """
    # Verify camera exists
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    # Get existing zone
    zone = await db.get(CameraAIConfig, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id} not found")

    # Verify zone belongs to camera
    if zone.camera_id != camera_id:
        raise HTTPException(
            status_code=400,
            detail=f"Zone {zone_id} does not belong to camera {camera_id}"
        )

    # Update fields
    update_data = zone_update.dict(exclude_unset=True)

    # Validate event_type if provided
    if 'event_type' in update_data:
        valid_event_types = ['intrusion', 'loitering', 'line_crossing', 'abandoned_object', 'crowd_detection']
        if update_data['event_type'] not in valid_event_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event_type. Must be one of: {', '.join(valid_event_types)}"
            )

    # Validate severity if provided
    if 'default_severity' in update_data:
        valid_severities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
        if update_data['default_severity'] not in valid_severities:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid severity. Must be one of: {', '.join(valid_severities)}"
            )

    # Validate ROI polygon if provided
    if 'roi_polygon' in update_data and update_data['roi_polygon']:
        if len(update_data['roi_polygon']) < 3:
            raise HTTPException(
                status_code=400,
                detail="ROI polygon must have at least 3 points"
            )
        for point in update_data['roi_polygon']:
            if len(point) != 2:
                raise HTTPException(
                    status_code=400,
                    detail="Each polygon point must be [x, y] coordinates"
                )
            if not (0 <= point[0] <= 1 and 0 <= point[1] <= 1):
                raise HTTPException(
                    status_code=400,
                    detail="Polygon coordinates must be normalized (0.0-1.0)"
                )

    # Validate confidence threshold if provided
    if 'confidence_threshold' in update_data:
        if not (0.0 <= update_data['confidence_threshold'] <= 1.0):
            raise HTTPException(
                status_code=400,
                detail="confidence_threshold must be between 0.0 and 1.0"
            )

    # Apply updates
    for field, value in update_data.items():
        setattr(zone, field, value)

    try:
        await db.commit()
        await db.refresh(zone)
        return zone
    except Exception as e:
        await db.rollback()
        if "unique_camera_event_config" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"Zone for event_type '{update_data.get('event_type')}' already exists for this camera"
            )
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.delete("/{camera_id}/zones/{zone_id}", status_code=204)
async def delete_camera_zone(
    camera_id: UUID,
    zone_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a zone configuration.

    - **camera_id**: UUID of the camera
    - **zone_id**: UUID of the zone configuration to delete
    """
    # Verify camera exists
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    # Get zone
    zone = await db.get(CameraAIConfig, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id} not found")

    # Verify zone belongs to camera
    if zone.camera_id != camera_id:
        raise HTTPException(
            status_code=400,
            detail=f"Zone {zone_id} does not belong to camera {camera_id}"
        )

    # Delete zone
    await db.delete(zone)
    await db.commit()
    return None
