from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from uuid import UUID
from datetime import datetime

# --- Permissions ---
class PermissionBase(BaseModel):
    slug: str
    description: Optional[str] = None

class PermissionCreate(PermissionBase):
    pass

class PermissionUpdate(BaseModel):
    slug: Optional[str] = None
    description: Optional[str] = None

class PermissionResponse(PermissionBase):
    id: UUID
    
    class Config:
        from_attributes = True

# --- Roles ---
class RoleBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    is_system_role: bool = False

class RoleCreate(RoleBase):
    permission_ids: List[UUID] = []

class RoleUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_system_role: Optional[bool] = None
    permission_ids: Optional[List[UUID]] = None

class RoleResponse(RoleBase):
    id: UUID
    permissions: List[PermissionResponse] = []

    class Config:
        from_attributes = True

# --- Users ---
class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool = True
    role_id: Optional[UUID] = None

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    role_id: Optional[UUID] = None
    password: Optional[str] = None # Optional password update

class UserResponse(UserBase):
    id: UUID
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    role: Optional[RoleResponse] = None

    class Config:
        from_attributes = True
