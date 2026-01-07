"""
Authentication endpoints for user login and token management.

Routes:
  - POST /api/v1/auth/login - User login with username/password
  - POST /api/v1/auth/refresh - Refresh access token
  - POST /api/v1/auth/logout - Invalidate token (client-side)
  - GET  /api/v1/auth/me - Get current user info
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import timedelta

from app.core.database import get_db
from app.models import User
from app.core.security import (
    verify_password,
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

router = APIRouter()
security = HTTPBearer()


# ============================================================================
# REQUEST/RESPONSE SCHEMAS
# ============================================================================

class LoginRequest(BaseModel):
    """Login request with username and password"""
    username: str
    password: str


class TokenResponse(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until expiration
    user: "UserInfo"


class UserInfo(BaseModel):
    """User information returned after login"""
    id: str
    username: str
    email: str
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class RefreshTokenRequest(BaseModel):
    """Request to refresh token (placeholder for future implementation)"""
    refresh_token: str


# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user and return JWT access token.

    **Usage:**
    ```bash
    curl -X POST http://localhost:8003/api/v1/auth/login \\
      -H "Content-Type: application/json" \\
      -d '{"username": "admin", "password": "your_password"}'
    ```

    **Response:**
    ```json
    {
      "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "token_type": "bearer",
      "expires_in": 1800,
      "user": {
        "id": "uuid-here",
        "username": "admin",
        "email": "admin@example.com",
        "full_name": "Administrator",
        "role": "ADMIN",
        "is_active": true
      }
    }
    ```

    **Errors:**
    - 401: Invalid credentials
    - 403: User account is inactive
    """
    # Find user by username
    result = await db.execute(
        select(User).where(User.username == credentials.username)
    )
    user = result.scalar_one_or_none()

    # Validate user exists and password is correct
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive. Please contact administrator."
        )

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "username": user.username,
            "email": user.email
        },
        expires_delta=access_token_expires
    )

    # Update last login timestamp
    from datetime import datetime
    user.last_login = datetime.now()
    await db.commit()

    # Return token and user info
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
        "user": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.code if user.role else None,
            "is_active": user.is_active
        }
    }


@router.get("/me", response_model=UserInfo)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    Get information about the currently authenticated user.

    **Usage:**
    ```bash
    curl -X GET http://localhost:8003/api/v1/auth/me \\
      -H "Authorization: Bearer YOUR_TOKEN_HERE"
    ```

    **Response:**
    ```json
    {
      "id": "uuid-here",
      "username": "admin",
      "email": "admin@example.com",
      "full_name": "Administrator",
      "role": "ADMIN",
      "is_active": true
    }
    ```

    **Errors:**
    - 401: Invalid or expired token
    """
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role.code if current_user.role else None,
        "is_active": current_user.is_active
    }


@router.post("/logout")
async def logout():
    """
    Logout endpoint (client-side token invalidation).

    Since JWT tokens are stateless, logout is handled client-side by
    discarding the token. This endpoint exists for API consistency.

    For server-side token revocation, implement a token blacklist
    (Redis-based) in future iterations.

    **Usage:**
    ```bash
    curl -X POST http://localhost:8003/api/v1/auth/logout \\
      -H "Authorization: Bearer YOUR_TOKEN_HERE"
    ```

    **Response:**
    ```json
    {
      "message": "Logged out successfully"
    }
    ```
    """
    return {
        "message": "Logged out successfully. Please discard your access token."
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    refresh_request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh access token using refresh token.

    **Note:** This is a placeholder implementation. In production, you should:
    1. Issue refresh tokens alongside access tokens during login
    2. Store refresh tokens in database with expiration
    3. Validate refresh token and issue new access token
    4. Implement rotation policy for refresh tokens

    **Future Enhancement:**
    ```python
    # Verify refresh token from database
    refresh_token = await get_refresh_token(refresh_request.refresh_token, db)

    # Create new access token
    new_access_token = create_access_token(...)

    # Optionally rotate refresh token
    new_refresh_token = create_refresh_token(...)

    return {access_token, refresh_token}
    ```
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Refresh token functionality not yet implemented. Please login again."
    )
