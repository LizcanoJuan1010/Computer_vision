"""
Zones API endpoints (nested under organizations)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.models import Organization, OrgZone
from app.api.routes.schemas_extended import (
    OrgZoneCreate,
    OrgZoneUpdate,
    OrgZoneResponse
)
from app.api.dependencies import get_organization_by_slug, get_zone_by_slug

router = APIRouter()


@router.get("/", response_model=List[OrgZoneResponse])
async def list_zones(
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db),
    include_inactive: bool = False
):
    """
    List all zones in an organization.

    - **org_slug**: Organization identifier
    - **include_inactive**: If true, includes inactive zones
    """
    query = select(OrgZone).where(OrgZone.organization_id == org.id)
    if not include_inactive:
        query = query.where(OrgZone.is_active == True)

    result = await db.execute(query.order_by(OrgZone.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=OrgZoneResponse, status_code=201)
async def create_zone(
    zone: OrgZoneCreate,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new zone in an organization.

    - **org_slug**: Organization identifier
    - **slug**: URL-friendly zone identifier (e.g., 'edificio-norte')
    - **name**: Display name of the zone
    - **location_description**: Optional text description
    - **geo_bounds**: Optional GeoJSON-like bounds object
    - **is_active**: Default true

    Slug validation: Must match pattern ^[a-z0-9]+(?:-[a-z0-9]+)*$
    Note: Slug must be unique within the organization
    """
    # Validate slug format
    import re
    if not re.match(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', zone.slug):
        raise HTTPException(
            status_code=400,
            detail="Slug must be lowercase alphanumeric with hyphens (e.g., 'bodega-principal')"
        )

    # Check if slug already exists in this organization
    existing = await db.execute(
        select(OrgZone).where(
            OrgZone.organization_id == org.id,
            OrgZone.slug == zone.slug
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Zone with slug '{zone.slug}' already exists in organization '{org.slug}'"
        )

    # Create zone
    new_zone = OrgZone(
        organization_id=org.id,
        **zone.dict()
    )
    db.add(new_zone)

    try:
        await db.commit()
        await db.refresh(new_zone)
        return new_zone
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


@router.get("/{zone_slug}", response_model=OrgZoneResponse)
async def get_zone(
    zone: OrgZone = Depends(get_zone_by_slug)
):
    """
    Get zone details by slug.

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier
    """
    return zone


@router.put("/{zone_slug}", response_model=OrgZoneResponse)
async def update_zone(
    zone_update: OrgZoneUpdate,
    zone: OrgZone = Depends(get_zone_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Update zone details.

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier
    - All fields are optional - only provided fields will be updated
    - Slug cannot be changed (immutable)
    """
    update_data = zone_update.dict(exclude_unset=True)

    # Apply updates
    for field, value in update_data.items():
        setattr(zone, field, value)

    try:
        await db.commit()
        await db.refresh(zone)
        return zone
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


@router.delete("/{zone_slug}", status_code=204)
async def delete_zone(
    zone: OrgZone = Depends(get_zone_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a zone (soft delete by setting is_active=False).

    - **org_slug**: Organization identifier
    - **zone_slug**: Zone identifier

    Note: This performs a soft delete. All cameras in this zone
    will also be cascade deleted due to ON DELETE CASCADE constraints.
    """
    # Soft delete
    zone.is_active = False

    try:
        await db.commit()
        return None
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )
