"""
Organizations API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.models import Organization
from app.api.routes.schemas_extended import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse
)
from app.api.dependencies import get_organization_by_slug

router = APIRouter()


@router.get("/", response_model=List[OrganizationResponse])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    include_inactive: bool = False
):
    """
    List all organizations.

    - **include_inactive**: If true, includes inactive organizations
    """
    query = select(Organization)
    if not include_inactive:
        query = query.where(Organization.is_active == True)

    result = await db.execute(query.order_by(Organization.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    org: OrganizationCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new organization.

    - **slug**: URL-friendly identifier (lowercase, alphanumeric, hyphens only)
    - **name**: Display name of the organization
    - **is_managed**: True for SaaS managed, False for on-premise
    - **config**: Optional JSON configuration object
    - **is_active**: Default true

    Slug validation: Must match pattern ^[a-z0-9]+(?:-[a-z0-9]+)*$
    """
    # Validate slug format
    import re
    if not re.match(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', org.slug):
        raise HTTPException(
            status_code=400,
            detail="Slug must be lowercase alphanumeric with hyphens (e.g., 'my-company')"
        )

    # Check if slug already exists
    existing = await db.execute(
        select(Organization).where(Organization.slug == org.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Organization with slug '{org.slug}' already exists"
        )

    # Create organization
    new_org = Organization(**org.dict())
    db.add(new_org)

    try:
        await db.commit()
        await db.refresh(new_org)
        return new_org
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


@router.get("/{org_slug}", response_model=OrganizationResponse)
async def get_organization(
    org: Organization = Depends(get_organization_by_slug)
):
    """
    Get organization details by slug.

    - **org_slug**: URL-friendly organization identifier
    """
    return org


@router.put("/{org_slug}", response_model=OrganizationResponse)
async def update_organization(
    org_update: OrganizationUpdate,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Update organization details.

    - **org_slug**: URL-friendly organization identifier
    - All fields are optional - only provided fields will be updated
    - Slug cannot be changed (immutable)
    """
    update_data = org_update.dict(exclude_unset=True)

    # Apply updates
    for field, value in update_data.items():
        setattr(org, field, value)

    try:
        await db.commit()
        await db.refresh(org)
        return org
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


@router.delete("/{org_slug}", status_code=204)
async def delete_organization(
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete an organization (soft delete by setting is_active=False).

    - **org_slug**: URL-friendly organization identifier

    Note: This performs a soft delete. All related zones and cameras
    will also be cascade deleted due to ON DELETE CASCADE constraints.
    """
    # Soft delete
    org.is_active = False

    try:
        await db.commit()
        return None
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )
