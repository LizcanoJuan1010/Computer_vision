from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
import asyncio
import logging
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from uuid import UUID

from app.core.database import get_db
from app.services.cache import router_cache
from app.models import User, Role, Permission, Camera, Event, Organization, OrgZone
from app.schemas import (
    UserCreate, UserUpdate, UserResponse,
    RoleCreate, RoleUpdate, RoleResponse,
    PermissionCreate, PermissionUpdate, PermissionResponse
)

router = APIRouter()

# --- System Summary ---
@router.get("/system/summary")
async def get_system_summary(db: AsyncSession = Depends(get_db)):
    """Returns a summary of system entities."""
    # Count Cameras
    res_cameras = await db.execute(select(func.count(Camera.id)))
    count_cameras = res_cameras.scalar()
    
    # Count Events
    res_events = await db.execute(select(func.count(Event.id)))
    count_events = res_events.scalar()
    
    # Count Users (TODO: Implement User/Role tables)
    # res_users = await db.execute(select(func.count(User.id)))
    count_users = 0 # res_users.scalar()
    
    # Count Roles
    # res_roles = await db.execute(select(func.count(Role.id)))
    count_roles = 0 # res_roles.scalar()
    
    return {
        "cameras": count_cameras,
        "events": count_events,
        "users": count_users,
        "roles": count_roles
    }

# --- Permissions CRUD ---
@router.post("/permissions", response_model=PermissionResponse)
async def create_permission(permission: PermissionCreate, db: AsyncSession = Depends(get_db)):
    db_perm = Permission(**permission.dict())
    db.add(db_perm)
    try:
        await db.commit()
        await db.refresh(db_perm)
        return db_perm
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/permissions", response_model=List[PermissionResponse])
async def list_permissions(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Permission).offset(skip).limit(limit))
    return result.scalars().all()

@router.get("/permissions/{perm_id}", response_model=PermissionResponse)
async def get_permission(perm_id: UUID, db: AsyncSession = Depends(get_db)):
    perm = await db.get(Permission, perm_id)
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    return perm

@router.put("/permissions/{perm_id}", response_model=PermissionResponse)
async def update_permission(perm_id: UUID, perm_update: PermissionUpdate, db: AsyncSession = Depends(get_db)):
    perm = await db.get(Permission, perm_id)
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    
    update_data = perm_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(perm, key, value)
    
    await db.commit()
    await db.refresh(perm)
    return perm

@router.delete("/permissions/{perm_id}")
async def delete_permission(perm_id: UUID, db: AsyncSession = Depends(get_db)):
    perm = await db.get(Permission, perm_id)
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    await db.delete(perm)
    await db.commit()
    return {"message": "Permission deleted"}

# --- Roles CRUD ---
@router.post("/roles", response_model=RoleResponse)
async def create_role(role: RoleCreate, db: AsyncSession = Depends(get_db)):
    # Create Role
    db_role = Role(
        code=role.code,
        name=role.name,
        description=role.description,
        is_system_role=role.is_system_role
    )
    db.add(db_role)
    
    # Add Permissions
    if role.permission_ids:
        stmt = select(Permission).where(Permission.id.in_(role.permission_ids))
        result = await db.execute(stmt)
        permissions = result.scalars().all()
        db_role.permissions = list(permissions)
        
    try:
        await db.commit()
        await db.refresh(db_role)
        
        # Manually construct response to avoid lazy loading issues
        return RoleResponse(
            id=db_role.id,
            code=db_role.code,
            name=db_role.name,
            description=db_role.description,
            is_system_role=db_role.is_system_role,
            permissions=[PermissionResponse.from_orm(p) for p in permissions] if role.permission_ids else []
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/roles", response_model=List[RoleResponse])
async def list_roles(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    # Eager load permissions
    from sqlalchemy.orm import selectinload
    result = await db.execute(select(Role).options(selectinload(Role.permissions)).offset(skip).limit(limit))
    return result.scalars().all()

@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(role_id: UUID, db: AsyncSession = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    result = await db.execute(select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role

@router.put("/roles/{role_id}", response_model=RoleResponse)
async def update_role(role_id: UUID, role_update: RoleUpdate, db: AsyncSession = Depends(get_db)):
    # Fetch with permissions
    from sqlalchemy.orm import selectinload
    result = await db.execute(select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    update_data = role_update.dict(exclude_unset=True)
    
    # Handle permissions update separately
    if "permission_ids" in update_data:
        perm_ids = update_data.pop("permission_ids")
        if perm_ids is not None:
            stmt = select(Permission).where(Permission.id.in_(perm_ids))
            res = await db.execute(stmt)
            perms = res.scalars().all()
            role.permissions = list(perms)
            
    for key, value in update_data.items():
        setattr(role, key, value)
        
    await db.commit()
    await db.refresh(role)
    return role

@router.delete("/roles/{role_id}")
async def delete_role(role_id: UUID, db: AsyncSession = Depends(get_db)):
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    await db.delete(role)
    await db.commit()
    return {"message": "Role deleted"}

# --- Users CRUD ---
@router.post("/users", response_model=UserResponse)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    # Hash password (TODO: Use proper hashing lib like passlib)
    # For now, simplistic hashing for demo
    import hashlib
    hashed_pw = hashlib.sha256(user.password.encode()).hexdigest()
    
    db_user = User(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        role_id=user.role_id,
        password_hash=hashed_pw
    )
    db.add(db_user)
    try:
        await db.commit()
        await db.refresh(db_user)
        
        # Manually construct response
        role_resp = None
        if user.role_id:
            # We need to fetch the role if we want to return it, or just return None if lazy loaded.
            # Since we just assigned role_id, db_user.role might be None until loaded.
            # Let's fetch it explicitly if needed, or just return the ID.
            # UserResponse expects a RoleResponse object.
            # For simplicity in creation, we can omit the full role object or fetch it.
            # Let's fetch it to be correct.
            role_obj = await db.get(Role, user.role_id)
            if role_obj:
                # We also need permissions for RoleResponse
                # This gets complicated. Let's just return the user without the full role object for now
                # OR fetch it properly.
                # Actually, let's just return the user. The response model has role as Optional.
                pass
        
        return UserResponse(
            id=db_user.id,
            username=db_user.username,
            email=db_user.email,
            full_name=db_user.full_name,
            is_active=db_user.is_active,
            role_id=db_user.role_id,
            created_at=db_user.created_at,
            updated_at=db_user.updated_at,
            last_login=db_user.last_login,
            role=None # Avoid lazy load of role
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/users", response_model=List[UserResponse])
async def list_users(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    # Eager load role AND role.permissions
    result = await db.execute(
        select(User)
        .options(selectinload(User.role).selectinload(Role.permissions))
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: UUID, db: AsyncSession = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    # Eager load role AND role.permissions
    result = await db.execute(
        select(User)
        .options(selectinload(User.role).selectinload(Role.permissions))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: UUID, user_update: UserUpdate, db: AsyncSession = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    result = await db.execute(select(User).options(selectinload(User.role)).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    update_data = user_update.dict(exclude_unset=True)
    
    if "password" in update_data:
        pw = update_data.pop("password")
        if pw:
            import hashlib
            user.password_hash = hashlib.sha256(pw.encode()).hexdigest()
            
    for key, value in update_data.items():
        setattr(user, key, value)
        
    await db.commit()
    await db.refresh(user)
    return user

@router.delete("/users/{user_id}")
async def delete_user(user_id: UUID, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
    return {"message": "User deleted"}


@router.get("/health")
async def health(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Advanced health check endpoint.
    Verifies connectivity to all critical services.
    """
    health_status = {
        "status": "ok",
        "services": {}
    }

    # Check Database
    try:
        await db.execute(select(func.count(Camera.id)))
        health_status["services"]["database"] = "ok"
    except Exception as e:
        health_status["services"]["database"] = f"error: {str(e)}"
        health_status["status"] = "degraded"

    # Check Redis
    try:
        if router_cache.redis:
            await router_cache.redis.ping()
            health_status["services"]["redis"] = "ok"
        else:
            health_status["services"]["redis"] = "not_connected"
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["services"]["redis"] = f"error: {str(e)}"
        health_status["status"] = "degraded"

    # Check NATS
    try:
        if hasattr(request.app.state, 'nc') and request.app.state.nc:
            if request.app.state.nc.is_connected:
                health_status["services"]["nats"] = "ok"
            else:
                health_status["services"]["nats"] = "disconnected"
                health_status["status"] = "degraded"
        else:
            health_status["services"]["nats"] = "not_initialized"
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["services"]["nats"] = f"error: {str(e)}"
        health_status["status"] = "degraded"

    # L1 Cache stats
    health_status["cache"] = {
        "l1_size": len(router_cache.l1),
        "l1_max": router_cache.l1.maxsize,
        "l1_ttl": router_cache.l1.ttl
    }

    return health_status

@router.post("/admin/cache/warmup")
async def cache_warmup(db: AsyncSession = Depends(get_db)):
    """
    Populates Redis cache with all active camera configurations from database.
    Supports multi-tenancy: reads org/zone from cameras.
    """
    from sqlalchemy.orm import selectinload

    # Load all active cameras with their zones and organizations
    result = await db.execute(
        select(Camera)
        .options(selectinload(Camera.zone).selectinload(OrgZone.organization))
        .where(Camera.is_active == True)
    )
    cameras = result.scalars().all()

    warmed_count = 0
    errors = []

    for camera in cameras:
        try:
            # Determine org/zone slugs
            org_slug = None
            zone_slug = None

            if camera.zone:
                zone_slug = camera.zone.slug
                if camera.zone.organization:
                    org_slug = camera.zone.organization.slug

            # Default services (can be customized per camera)
            services = ["security"]  # Default service

            # Populate Redis cache
            await router_cache.set_config(
                camera_id=str(camera.id),
                services=services,
                org_slug=org_slug,
                zone_slug=zone_slug
            )
            warmed_count += 1

        except Exception as e:
            errors.append({
                "camera_id": str(camera.id),
                "error": str(e)
            })

    return {
        "status": "completed",
        "cameras_warmed": warmed_count,
        "total_cameras": len(cameras),
        "errors": errors
    }

@router.post("/config/{camera_id}")
async def update_config(camera_id: str, services: List[str]):
    """
    Updates configuration for a camera (writes to Redis + invalidates L1).
    Legacy endpoint - for multi-tenancy use admin endpoints.
    """
    await router_cache.set_config(camera_id, services)
    return {"status": "updated", "camera_id": camera_id, "services": services}

@router.get("/debug/routes/{camera_id}")
async def get_routes(camera_id: str):
    """
    Debug endpoint: Shows active services for a camera.
    Legacy format - does not include org/zone context.
    """
    services = await router_cache.get_services(camera_id)
    return {"camera_id": camera_id, "active_services": list(services)}

# --- Video Streaming (DEPRECATED - Use /api/v1/stream) ---
# @router.get("/stream/{camera_id}")
# async def stream_video(camera_id: str, request: Request):
#    pass

