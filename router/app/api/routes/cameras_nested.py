"""
Nested Cameras API endpoints (under organizations and zones)
Route: /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.models import Camera, OrgZone, CameraAIConfig
from app.api.routes.schemas_extended import (
    CameraCreate,
    CameraResponse,
    CameraAIConfigCreate,
    CameraAIConfigUpdate,
    CameraAIConfigResponse
)
from app.api.dependencies import get_zone_by_slug, get_camera_in_zone

router = APIRouter()


@router.get("/", response_model=List[CameraResponse])
async def list_cameras_in_zone(
    zone: OrgZone = Depends(get_zone_by_slug),
    db: AsyncSession = Depends(get_db),
    include_inactive: bool = False
):
    """
    List all cameras in a specific zone.

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier
    - **include_inactive**: If true, includes inactive cameras
    """
    query = select(Camera).where(Camera.zone_id == zone.id)
    if not include_inactive:
        query = query.where(Camera.is_active == True)

    result = await db.execute(query.order_by(Camera.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=CameraResponse, status_code=201)
async def create_camera_in_zone(
    camera: CameraCreate,
    request: Request,
    zone: OrgZone = Depends(get_zone_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new camera in a specific zone.

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier
    - **name**: Camera name
    - **rtsp_url**: RTSP stream URL
    - **location_name**: Optional location description
    - **meta_info**: Optional metadata JSON object

    Note: zone_id will be automatically set to the current zone
    """
    # Create camera data and override zone_id to ensure it matches the URL
    camera_data = camera.dict()
    camera_data['zone_id'] = zone.id

    new_camera = Camera(**camera_data)
    db.add(new_camera)

    try:
        await db.commit()
        await db.refresh(new_camera)

        # --- NATS Integration: Start Camera ---
        try:
            if hasattr(request.app.state, "nc"):
                nc = request.app.state.nc
                if nc and nc.is_connected:
                    import json
                    cmd = {"camera_id": str(new_camera.id)}
                    subject = f"commands.camera.{new_camera.id}.start"
                    await nc.publish(subject, json.dumps(cmd).encode())
                    # print(f"🚀 Sent start command for camera {new_camera.id}")
        except Exception as e:
            # Don't fail the request if NATS fails, just log it
            print(f"⚠️ Failed to send NATS start command: {e}")

        return new_camera
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera: Camera = Depends(get_camera_in_zone)
):
    """
    Get camera details by ID within a specific zone.

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier
    - **camera_id**: Camera UUID
    """
    return camera


@router.put("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: UUID,
    camera_update: CameraCreate,
    zone: OrgZone = Depends(get_zone_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Update camera details.

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier
    - **camera_id**: Camera UUID
    - All fields from CameraCreate can be updated

    Note: Camera will remain in the current zone (zone_id cannot be changed via this endpoint)
    """
    camera = await db.get(Camera, camera_id)

    if not camera:
        raise HTTPException(
            status_code=404,
            detail=f"Camera {camera_id} not found"
        )

    if camera.zone_id != zone.id:
        raise HTTPException(
            status_code=400,
            detail=f"Camera {camera_id} does not belong to zone '{zone.slug}'"
        )

    # Update fields (excluding zone_id to prevent moving between zones)
    update_data = camera_update.dict(exclude={'zone_id'})
    for field, value in update_data.items():
        setattr(camera, field, value)

    try:
        await db.commit()
        await db.refresh(camera)
        return camera
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(
    request: Request,
    camera: Camera = Depends(get_camera_in_zone),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a camera (soft delete by setting is_active=False).

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier
    - **camera_id**: Camera UUID

    Note: This performs a soft delete. All related AI configs and events
    will be preserved for historical records.
    """
    # Soft delete
    camera.is_active = False

    try:
        await db.commit()
        
        # --- NATS Integration: Stop Camera ---
        try:
            if hasattr(request.app.state, "nc"):
                nc = request.app.state.nc
                if nc and nc.is_connected:
                    import json
                    cmd = {"camera_id": str(camera.id)}
                    subject = f"commands.camera.{camera.id}.stop"
                    await nc.publish(subject, json.dumps(cmd).encode())
        except Exception as e:
             print(f"⚠️ Failed to send NATS stop command: {e}")

        return None
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


# --- AI Zone Configuration Endpoints (nested under cameras) ---

@router.get("/{camera_id}/zones", response_model=List[CameraAIConfigResponse])
async def get_camera_ai_zones(
    camera: Camera = Depends(get_camera_in_zone),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all AI zone configurations for a specific camera.

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier (geographic zone)
    - **camera_id**: Camera UUID
    - Returns: List of AI zone configurations with ROI polygons, event types, and settings

    Note: "zones" here refers to AI detection zones (ROI polygons), not geographic zones
    """
    result = await db.execute(
        select(CameraAIConfig).where(CameraAIConfig.camera_id == camera.id)
    )
    return result.scalars().all()


@router.post("/{camera_id}/zones", response_model=CameraAIConfigResponse, status_code=201)
async def create_camera_ai_zone(
    zone_config: CameraAIConfigCreate,
    camera: Camera = Depends(get_camera_in_zone),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new AI zone configuration for a camera.

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier (geographic zone)
    - **camera_id**: Camera UUID
    - **event_type**: Type of event to detect (intrusion, loitering, line_crossing, etc.)
    - **roi_polygon**: List of [x, y] coordinates defining the region of interest
    - **confidence_threshold**: Minimum confidence (0.0-1.0) to trigger event
    - **debounce_seconds**: Minimum time between consecutive events
    - **default_severity**: CRITICAL, HIGH, MEDIUM, LOW, INFO

    Note: Only one AI zone per camera per event_type (enforced by DB constraint)
    """
    # Validate event_type
    valid_event_types = [
        'intrusion', 'loitering', 'line_crossing', 'abandoned_object', 'crowd_detection', 'face',
        'fall_detection', 'fight_detection', 'compliance_smoking', 'compliance_calling',
        'forensics', 'reid', 'lpr', 'human_attr', 'vehicle_attr'
    ]
    if zone_config.event_type not in valid_event_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type. Must be one of: {', '.join(valid_event_types)}"
        )

    # Validate severity
    valid_severities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
    if zone_config.default_severity not in valid_severities:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid severity. Must be one of: {', '.join(valid_severities)}"
        )

    # Validate ROI polygon if provided
    if zone_config.roi_polygon:
        if len(zone_config.roi_polygon) < 3:
            raise HTTPException(
                status_code=400,
                detail="ROI polygon must have at least 3 points"
            )
        for point in zone_config.roi_polygon:
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
    if not (0.0 <= zone_config.confidence_threshold <= 1.0):
        raise HTTPException(
            status_code=400,
            detail="confidence_threshold must be between 0.0 and 1.0"
        )

    # Create new AI zone
    try:
        new_zone = CameraAIConfig(
            camera_id=camera.id,
            **zone_config.dict()
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
                detail=f"AI zone for event_type '{zone_config.event_type}' already exists for this camera"
            )
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.put("/{camera_id}/zones/{zone_id}", response_model=CameraAIConfigResponse)
async def update_camera_ai_zone(
    zone_id: UUID,
    zone_update: CameraAIConfigUpdate,
    camera: Camera = Depends(get_camera_in_zone),
    db: AsyncSession = Depends(get_db)
):
    """
    Update an existing AI zone configuration.

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier (geographic zone)
    - **camera_id**: Camera UUID
    - **zone_id**: AI zone configuration UUID to update
    - All fields are optional - only provided fields will be updated
    """
    # Get existing AI zone
    ai_zone = await db.get(CameraAIConfig, zone_id)
    if not ai_zone:
        raise HTTPException(status_code=404, detail=f"AI zone {zone_id} not found")

    # Verify AI zone belongs to camera
    if ai_zone.camera_id != camera.id:
        raise HTTPException(
            status_code=400,
            detail=f"AI zone {zone_id} does not belong to camera {camera.id}"
        )

    # Update fields
    update_data = zone_update.dict(exclude_unset=True)

    # Validate event_type if provided
    if 'event_type' in update_data:
        valid_event_types = [
            'intrusion', 'loitering', 'line_crossing', 'abandoned_object', 'crowd_detection', 'face',
            'fall_detection', 'fight_detection', 'compliance_smoking', 'compliance_calling',
            'forensics', 'reid', 'lpr', 'human_attr', 'vehicle_attr'
        ]
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
        setattr(ai_zone, field, value)

    try:
        await db.commit()
        await db.refresh(ai_zone)
        return ai_zone
    except Exception as e:
        await db.rollback()
        if "unique_camera_event_config" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"AI zone for event_type '{update_data.get('event_type')}' already exists for this camera"
            )
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.delete("/{camera_id}/zones/{zone_id}", status_code=204)
async def delete_camera_ai_zone(
    zone_id: UUID,
    camera: Camera = Depends(get_camera_in_zone),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete an AI zone configuration.

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier (geographic zone)
    - **camera_id**: Camera UUID
    - **zone_id**: AI zone configuration UUID to delete
    """
    # Get AI zone
    ai_zone = await db.get(CameraAIConfig, zone_id)
    if not ai_zone:
        raise HTTPException(status_code=404, detail=f"AI zone {zone_id} not found")

    # Verify AI zone belongs to camera
    if ai_zone.camera_id != camera.id:
        raise HTTPException(
            status_code=400,
            detail=f"AI zone {zone_id} does not belong to camera {camera.id}"
        )

    # Delete AI zone
    await db.delete(ai_zone)
    await db.commit()
    return None
