"""
Events/Alarms Multi-tenancy API endpoints
Routes:
  - GET  /api/v1/orgs/{org_slug}/events/
  - GET  /api/v1/orgs/{org_slug}/zones/{zone_slug}/events/
  - GET  /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/events/
  - GET  /api/v1/events/{id}
  - PUT  /api/v1/events/{id}/status
  - POST /api/v1/events/{id}/actions
  - GET  /api/v1/events/{id}/video
  - GET  /api/v1/events/{id}/snapshot
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import os

from app.core.database import get_db
from app.models import Event, Camera, OrgZone, Organization, EventAction, EventStatus, User
from app.api.routes.schemas_extended import EventResponse, EventStatusUpdate, EventActionCreate, EventActionResponse
from app.api.dependencies import get_organization_by_slug, get_zone_by_slug, get_camera_in_zone, get_current_user

router = APIRouter()


@router.get("/orgs/{org_slug}/events/", response_model=List[EventResponse])
async def list_events_by_organization(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = None,
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None
):
    """
    List all events for a specific organization.

    Filters:
    - **status**: Filter by status (PENDING, ACKNOWLEDGED, RESOLVED, FALSE_POSITIVE)
    - **severity**: Filter by severity (CRITICAL, HIGH, MEDIUM, LOW, INFO)
    - **event_type**: Filter by event type (intrusion, loitering, etc.)
    - **from_date**: Filter events from this date onwards
    - **to_date**: Filter events until this date
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return (max 500)
    """
    # Verify organization exists
    org_result = await db.execute(
        select(Organization).where(
            and_(
                Organization.slug == org_slug,
                Organization.is_active == True
            )
        )
    )
    org = org_result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization '{org_slug}' not found")

    # Build query: Join events with cameras, zones, and organizations
    query = (
        select(Event)
        .join(Camera, Event.camera_id == Camera.id)
        .join(OrgZone, Camera.zone_id == OrgZone.id)
        .join(Organization, OrgZone.organization_id == Organization.id)
        .where(Organization.id == org.id)
    )

    # Apply filters
    if status:
        query = query.where(Event.status == status)
    if severity:
        query = query.where(Event.severity == severity)
    if event_type:
        query = query.where(Event.event_type == event_type)
    if from_date:
        query = query.where(Event.occurred_at >= from_date)
    if to_date:
        query = query.where(Event.occurred_at <= to_date)

    # Order by most recent first
    query = query.order_by(Event.occurred_at.desc())

    # Apply pagination
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/orgs/{org_slug}/zones/{zone_slug}/events/", response_model=List[EventResponse])
async def list_events_by_zone(
    zone: OrgZone = Depends(get_zone_by_slug),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = None,
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None
):
    """
    List all events for a specific zone.

    Filters: Same as organization endpoint
    """
    # Build query
    query = (
        select(Event)
        .join(Camera, Event.camera_id == Camera.id)
        .where(Camera.zone_id == zone.id)
    )

    # Apply filters
    if status:
        query = query.where(Event.status == status)
    if severity:
        query = query.where(Event.severity == severity)
    if event_type:
        query = query.where(Event.event_type == event_type)
    if from_date:
        query = query.where(Event.occurred_at >= from_date)
    if to_date:
        query = query.where(Event.occurred_at <= to_date)

    query = query.order_by(Event.occurred_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}/events/", response_model=List[EventResponse])
async def list_events_by_camera(
    camera: Camera = Depends(get_camera_in_zone),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = None,
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None
):
    """
    List all events for a specific camera.

    Filters: Same as organization endpoint
    """
    query = select(Event).where(Event.camera_id == camera.id)

    # Apply filters
    if status:
        query = query.where(Event.status == status)
    if severity:
        query = query.where(Event.severity == severity)
    if event_type:
        query = query.where(Event.event_type == event_type)
    if from_date:
        query = query.where(Event.occurred_at >= from_date)
    if to_date:
        query = query.where(Event.occurred_at <= to_date)

    query = query.order_by(Event.occurred_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/events/{event_id}", response_model=EventResponse)
async def get_event_detail(
    event_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information about a specific event.

    Returns:
    - Event details including camera_id, confidence, bbox, etc.
    - Snapshot and video clip paths (if available)
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    return event


@router.put("/events/{event_id}/status", response_model=EventResponse)
async def update_event_status(
    event_id: UUID,
    status_update: EventStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update the status of an event.

    Valid status transitions:
    - PENDING → ACKNOWLEDGED
    - PENDING → FALSE_POSITIVE
    - ACKNOWLEDGED → RESOLVED
    - ACKNOWLEDGED → FALSE_POSITIVE

    Body:
    - **new_status**: New status (ACKNOWLEDGED, RESOLVED, FALSE_POSITIVE)
    - **comment**: Optional comment explaining the status change
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    # Validate status transition
    valid_transitions = {
        "PENDING": ["ACKNOWLEDGED", "FALSE_POSITIVE"],
        "ACKNOWLEDGED": ["RESOLVED", "FALSE_POSITIVE"],
        "RESOLVED": [],
        "FALSE_POSITIVE": []
    }

    if status_update.new_status not in valid_transitions.get(event.status, []):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition: {event.status} → {status_update.new_status}"
        )

    # Store previous status
    previous_status = event.status

    # Update event status
    event.status = status_update.new_status

    # Create action record
    action = EventAction(
        event_id=event.id,
        user_id=current_user.id,
        previous_status=previous_status,
        new_status=status_update.new_status,
        comment=status_update.comment
    )
    db.add(action)

    try:
        await db.commit()
        await db.refresh(event)
        return event
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.post("/events/{event_id}/actions", response_model=EventActionResponse, status_code=201)
async def create_event_action(
    event_id: UUID,
    action: EventActionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Register an action taken on an event (without changing status).

    Use this endpoint to log actions like:
    - "Dispatched security guard to location"
    - "Contacted local authorities"
    - "Verified false positive via CCTV review"

    Body:
    - **comment**: Description of the action taken
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    new_action = EventAction(
        event_id=event.id,
        user_id=current_user.id,
        previous_status=event.status,
        new_status=event.status,  # Status unchanged
        comment=action.comment
    )
    db.add(new_action)

    try:
        await db.commit()
        await db.refresh(new_action)
        return new_action
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/events/{event_id}/snapshot")
async def download_event_snapshot(
    event_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Download the snapshot image associated with an event.

    Returns:
    - Image file (JPEG) if available
    - 404 if event or snapshot not found
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    if not event.snapshot_path:
        raise HTTPException(status_code=404, detail="No snapshot available for this event")

    # Check if file exists
    if not os.path.exists(event.snapshot_path):
        raise HTTPException(status_code=404, detail="Snapshot file not found on disk")

    return FileResponse(
        event.snapshot_path,
        media_type="image/jpeg",
        filename=f"event_{event_id}_snapshot.jpg"
    )


@router.get("/events/{event_id}/video")
async def download_event_video(
    event_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Download the video clip associated with an event.

    Returns:
    - Video file (MP4) if available
    - 404 if event or video not found
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    if not event.video_clip_path:
        raise HTTPException(status_code=404, detail="No video clip available for this event")

    # Check if file exists
    if not os.path.exists(event.video_clip_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    return FileResponse(
        event.video_clip_path,
        media_type="video/mp4",
        filename=f"event_{event_id}_clip.mp4"
    )
