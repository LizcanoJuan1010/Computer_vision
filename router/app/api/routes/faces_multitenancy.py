"""
Facial Recognition Multi-tenancy API endpoints
Routes:
  - GET    /api/v1/orgs/{org_slug}/faces/
  - POST   /api/v1/orgs/{org_slug}/faces/
  - GET    /api/v1/orgs/{org_slug}/faces/{face_id}
  - PUT    /api/v1/orgs/{org_slug}/faces/{face_id}
  - DELETE /api/v1/orgs/{org_slug}/faces/{face_id}
  - POST   /api/v1/orgs/{org_slug}/faces/search
  - GET    /api/v1/orgs/{org_slug}/faces/{face_id}/events
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text
from typing import List, Optional
from uuid import UUID
import base64
import json
import logging
import asyncio
import os
from datetime import datetime

from app.core.database import get_db
from app.models import Face, Organization, Event, Camera, OrgZone, BlacklistSharingLog
from app.api.routes.schemas_extended import (
    FaceCreateMultitenancy,
    FaceUpdateMultitenancy,
    FaceResponseMultitenancy,
    FaceSearchRequest,
    FaceSearchResult,
    EventResponse
)
from app.api.dependencies import get_organization_by_slug

router = APIRouter()
logger = logging.getLogger("router.faces_multitenancy")


@router.get("/orgs/{org_slug}/faces/", response_model=List[FaceResponseMultitenancy])
async def list_faces_by_organization(
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db),
    category: Optional[str] = Query(None, description="Filter by category: KNOWN, BLACKLIST, UNKNOWN"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500)
):
    """
    List all registered faces for a specific organization.

    Filters:
    - **category**: Filter by face category (KNOWN, BLACKLIST, UNKNOWN)
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return (max 500)
    """
    query = select(Face).where(Face.organization_id == org.id)

    if category:
        valid_categories = ['KNOWN', 'BLACKLIST', 'UNKNOWN']
        if category not in valid_categories:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
            )
        query = query.where(Face.category == category)

    query = query.order_by(Face.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.post("/orgs/{org_slug}/faces/", response_model=FaceResponseMultitenancy, status_code=201)
async def register_face_in_organization(
    org_slug: str,
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    category: str = Form("KNOWN"),
    meta_info: Optional[str] = Form("{}"),
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new face for an organization.

    Parameters:
    - **file**: Image file containing the face (JPEG, PNG)
    - **name**: Name or identifier for this face
    - **category**: KNOWN (authorized person) or BLACKLIST (unauthorized)
    - **meta_info**: Optional JSON metadata (employee_id, department, etc.)

    Process:
    1. Validates image format
    2. Sends to inference service for embedding extraction
    3. Stores face in database with organization link
    4. Saves image to filesystem for training
    """
    # Validate file type
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Must be an image.")

    # Validate category
    valid_categories = ['KNOWN', 'BLACKLIST', 'UNKNOWN']
    if category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
        )

    # Parse meta_info JSON
    try:
        meta_dict = json.loads(meta_info)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in meta_info")

    # Read file content
    content = await file.read()
    img_b64 = base64.b64encode(content).decode('utf-8')

    # Send to inference service via NATS
    nc = request.app.state.nc
    if not nc:
        raise HTTPException(status_code=503, detail="NATS unavailable")

    payload = {
        "name": name,
        "image": img_b64,
        "organization_id": str(org.id),
        "category": category,
        "meta_info": meta_dict
    }

    try:
        # Request-Reply pattern to get embedding
        response = await nc.request("commands.register_face", json.dumps(payload).encode(), timeout=10.0)
        res_data = json.loads(response.data.decode())

        if res_data.get("status") == "error":
            raise HTTPException(status_code=400, detail=res_data.get("message"))

        # Get face_id from response
        face_id = res_data.get("face_id")
        if not face_id:
            raise HTTPException(status_code=500, detail="Inference service did not return face_id")

        # Retrieve the created face from database
        face = await db.get(Face, face_id)
        if not face:
            raise HTTPException(status_code=500, detail="Face was registered but not found in database")

        return face

    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Inference service timed out")
    except Exception as e:
        logger.error(f"Face registration error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orgs/{org_slug}/faces/{face_id}", response_model=FaceResponseMultitenancy)
async def get_face(
    face_id: int,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information about a specific face.
    """
    face = await db.get(Face, face_id)
    if not face:
        raise HTTPException(status_code=404, detail=f"Face {face_id} not found")

    # Verify face belongs to organization
    if face.organization_id != org.id:
        raise HTTPException(
            status_code=403,
            detail=f"Face {face_id} does not belong to organization '{org.slug}'"
        )

    return face


@router.put("/orgs/{org_slug}/faces/{face_id}", response_model=FaceResponseMultitenancy)
async def update_face_metadata(
    face_id: int,
    face_update: FaceUpdateMultitenancy,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Update face metadata (name, category, meta_info).

    Note: This does NOT update the face embedding. To change the embedding,
    delete the face and register a new one.

    Fields that can be updated:
    - **name**: Person's name or identifier
    - **category**: KNOWN, BLACKLIST, UNKNOWN
    - **meta_info**: Additional metadata JSON
    """
    face = await db.get(Face, face_id)
    if not face:
        raise HTTPException(status_code=404, detail=f"Face {face_id} not found")

    # Verify ownership
    if face.organization_id != org.id:
        raise HTTPException(
            status_code=403,
            detail=f"Face {face_id} does not belong to organization '{org.slug}'"
        )

    # Update fields
    update_data = face_update.dict(exclude_unset=True)

    # Validate category if provided
    if 'category' in update_data:
        valid_categories = ['KNOWN', 'BLACKLIST', 'UNKNOWN']
        if update_data['category'] not in valid_categories:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
            )

    for field, value in update_data.items():
        setattr(face, field, value)

    try:
        await db.commit()
        await db.refresh(face)
        return face
    except Exception as e:
        await db.rollback()
        logger.error(f"Update face error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.delete("/orgs/{org_slug}/faces/{face_id}", status_code=204)
async def delete_face(
    face_id: int,
    request: Request,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a registered face from the organization.

    This will:
    1. Remove the face from the database (including embedding)
    2. Delete the stored image file (if exists)
    3. Notify inference service to reload face database
    """
    face = await db.get(Face, face_id)
    if not face:
        raise HTTPException(status_code=404, detail=f"Face {face_id} not found")

    # Verify ownership
    if face.organization_id != org.id:
        raise HTTPException(
            status_code=403,
            detail=f"Face {face_id} does not belong to organization '{org.slug}'"
        )

    # Delete image file if exists
    if face.image_path and os.path.exists(face.image_path):
        try:
            os.remove(face.image_path)
        except Exception as e:
            logger.warning(f"Could not delete image file {face.image_path}: {e}")

    # Delete from database
    await db.delete(face)
    await db.commit()

    # Notify inference service to reload faces
    nc = request.app.state.nc
    if nc:
        try:
            await nc.publish(
                "commands.reload_faces",
                json.dumps({"organization_id": str(org.id)}).encode()
            )
        except Exception as e:
            logger.warning(f"Could not notify inference service: {e}")

    return None


@router.post("/orgs/{org_slug}/faces/search", response_model=FaceSearchResult)
async def search_face_by_image(
    org_slug: str,
    request: Request,
    file: UploadFile = File(...),
    threshold: float = Form(0.6, description="Similarity threshold (0.0-1.0)"),
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Search for a face in the organization's database using an uploaded image.

    Process:
    1. Extracts embedding from uploaded image
    2. Searches organization's face database using cosine similarity
    3. Returns closest matches above threshold

    Parameters:
    - **file**: Image file containing the face to search
    - **threshold**: Minimum similarity score (0.0-1.0, default 0.6)

    Returns:
    - List of matching faces with similarity scores
    - Empty list if no matches found
    """
    # Validate file type
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Must be an image.")

    # Validate threshold
    if not (0.0 <= threshold <= 1.0):
        raise HTTPException(status_code=400, detail="Threshold must be between 0.0 and 1.0")

    # Read file content
    content = await file.read()
    img_b64 = base64.b64encode(content).decode('utf-8')

    # Send to inference service for search
    nc = request.app.state.nc
    if not nc:
        raise HTTPException(status_code=503, detail="NATS unavailable")

    payload = {
        "image": img_b64,
        "organization_id": str(org.id),
        "threshold": threshold
    }

    try:
        response = await nc.request("commands.search_face", json.dumps(payload).encode(), timeout=10.0)
        res_data = json.loads(response.data.decode())

        if res_data.get("status") == "error":
            raise HTTPException(status_code=400, detail=res_data.get("message"))

        return res_data

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Inference service timed out")
    except Exception as e:
        logger.error(f"Face search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orgs/{org_slug}/faces/{face_id}/events", response_model=List[EventResponse])
async def get_events_for_face(
    face_id: int,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None
):
    """
    Get all events where this face was detected.

    Useful for:
    - Tracking when/where a person was seen
    - Investigating blacklist detections
    - Analyzing movement patterns

    Filters:
    - **from_date**: Filter events from this date onwards
    - **to_date**: Filter events until this date
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return (max 500)
    """
    # Verify face exists and belongs to organization
    face = await db.get(Face, face_id)
    if not face:
        raise HTTPException(status_code=404, detail=f"Face {face_id} not found")

    if face.organization_id != org.id:
        raise HTTPException(
            status_code=403,
            detail=f"Face {face_id} does not belong to organization '{org.slug}'"
        )

    # Query events where this face was detected
    # Note: This assumes events table has a face_id column or we store face info in meta_info
    # For now, we'll search in event meta_info or bbox data
    # TODO: Add face_id column to events table for direct linking

    query = (
        select(Event)
        .join(Camera, Event.camera_id == Camera.id)
        .join(OrgZone, Camera.zone_id == OrgZone.id)
        .where(
            and_(
                OrgZone.organization_id == org.id,
                Event.event_type == 'face_recognition',
                Event.track_id == face.name  # Link via Name
            )
        )
    )

    # Apply date filters
    if from_date:
        query = query.where(Event.occurred_at >= from_date)
    if to_date:
        query = query.where(Event.occurred_at <= to_date)

    query = query.order_by(Event.occurred_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    events = result.scalars().all()

    # Filter events where this specific face was detected
    # This requires checking meta_info or a dedicated field
    # For now, return all face_recognition events (to be refined)

    return events


# --- Global Blacklist Management ---

@router.post("/orgs/{org_slug}/faces/{face_id}/share-to-global", status_code=200)
async def share_face_to_global_blacklist(
    face_id: int,
    request: Request,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Share a face to the Global Blacklist.
    This makes the face detectable by ALL organizations as a BLACKLIST threat.
    """
    # 1. Get Face
    face = await db.get(Face, face_id)
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")
    
    if face.organization_id != org.id:
        raise HTTPException(status_code=403, detail="Face does not belong to this organization")
    
    # 2. Update Face
    face.is_global_blacklist = True
    face.category = 'BLACKLIST' # Force category to BLACKLIST
    
    # 3. Log Action (Audit)
    log_entry = BlacklistSharingLog(
        face_id=face.id,
        shared_by_org_id=org.id,
        action='SHARED'
    )
    db.add(log_entry)

    await db.commit()
    await db.refresh(face)

    # 4. Notify Inference (NATS)
    nc = request.app.state.nc
    if nc:
        try:
            await nc.publish(
                "events.face.shared_to_global",
                json.dumps({
                    "face_id": face.id,
                    "org_id": str(org.id),
                    "action": "SHARED"
                }).encode()
            )
        except Exception as e:
            logger.warning(f"Failed to publish NATS event: {e}")

    return {"status": "success", "message": "Face shared to global blacklist", "face": face}


@router.delete("/orgs/{org_slug}/faces/{face_id}/unshare-from-global", status_code=200)
async def unshare_face_from_global_blacklist(
    face_id: int,
    request: Request,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Remove time face from Global Blacklist.
    It reverts to being a local BLACKLIST face for this organization only.
    """
    face = await db.get(Face, face_id)
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")
        
    if face.organization_id != org.id:
        raise HTTPException(status_code=403, detail="Face does not belong to this organization")
    
    if not face.is_global_blacklist:
        return {"status": "ignored", "message": "Face was not in global blacklist"}

    # Update
    face.is_global_blacklist = False
    
    # Log
    log_entry = BlacklistSharingLog(
        face_id=face.id,
        shared_by_org_id=org.id,
        action='UNSHARED'
    )
    db.add(log_entry)

    await db.commit()
    await db.refresh(face)

    # Notify
    nc = request.app.state.nc
    if nc:
        try:
            await nc.publish(
                "events.face.shared_to_global",
                json.dumps({
                    "face_id": face.id,
                    "org_id": str(org.id),
                    "action": "UNSHARED"
                }).encode()
            )
        except Exception as e:
            logger.warning(f"Failed to publish NATS event: {e}")

    return {"status": "success", "message": "Face removed from global blacklist"}


@router.get("/faces/global-blacklist", response_model=List[FaceResponseMultitenancy])
async def list_global_blacklist(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500)
):
    """
    List all faces currently in the Global Blacklist (from all organizations).
    """
    # Note: This might need admin permissions in the future
    query = select(Face).where(Face.is_global_blacklist == True)
    query = query.order_by(Face.created_at.desc()).offset(skip).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()
