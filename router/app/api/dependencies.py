"""
API Dependencies for multi-tenancy validation and authentication
"""
from fastapi import HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.core.database import get_db
from app.models import Organization, OrgZone, Camera, User

# Import authentication dependencies
from app.core.security import get_current_user, get_current_active_user, require_role


async def get_organization_by_slug(
    org_slug: str,
    db: AsyncSession = Depends(get_db)
) -> Organization:
    """
    Dependency to validate and retrieve organization by slug.
    Raises 404 if organization not found or inactive.
    """
    result = await db.execute(
        select(Organization).where(
            Organization.slug == org_slug,
            Organization.is_active == True
        )
    )
    org = result.scalar_one_or_none()

    if not org:
        raise HTTPException(
            status_code=404,
            detail=f"Organization '{org_slug}' not found or inactive"
        )

    return org


async def get_zone_by_slug(
    org_slug: str,
    zone_slug: str,
    db: AsyncSession = Depends(get_db)
) -> OrgZone:
    """
    Dependency to validate and retrieve zone by slug within an organization.
    Raises 404 if zone not found or inactive.
    """
    # First verify organization exists
    org = await get_organization_by_slug(org_slug, db)

    # Then get the zone
    result = await db.execute(
        select(OrgZone).where(
            OrgZone.organization_id == org.id,
            OrgZone.slug == zone_slug,
            OrgZone.is_active == True
        )
    )
    zone = result.scalar_one_or_none()

    if not zone:
        raise HTTPException(
            status_code=404,
            detail=f"Zone '{zone_slug}' not found in organization '{org_slug}' or inactive"
        )

    return zone


async def get_camera_in_zone(
    camera_id: UUID,
    zone: OrgZone = Depends(get_zone_by_slug),
    db: AsyncSession = Depends(get_db)
) -> Camera:
    """
    Dependency to validate and retrieve camera within a specific zone.
    Raises 404 if camera not found or doesn't belong to the zone.
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

    return camera
