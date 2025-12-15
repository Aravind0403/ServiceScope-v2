"""
Tenant Pydantic Schemas

Request/response models for Tenant and User operations.
"""

from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from uuid import UUID

from app.schemas.base import BaseResponse


# ===== Tenant Schemas =====

class TenantBase(BaseModel):
    """Base tenant fields."""
    name: str = Field(..., min_length=1, max_length=255,
                      description="Organization name")


class TenantCreate(TenantBase):
    """Schema for creating a tenant."""
    pass


class TenantUpdate(BaseModel):
    """Schema for updating a tenant."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_active: Optional[bool] = None
    rate_limit_rpm: Optional[int] = Field(None, ge=1, le=1000)
    max_repositories: Optional[int] = Field(None, ge=1, le=100)


class TenantResponse(TenantBase, BaseResponse):
    """Schema for tenant response."""
    api_key: str
    is_active: bool
    rate_limit_rpm: int
    max_repositories: int

    model_config = ConfigDict(from_attributes=True)


# ===== User Schemas =====

class UserBase(BaseModel):
    """Base user fields."""
    email: EmailStr = Field(..., description="User email address")
    full_name: Optional[str] = Field(None, max_length=255, description="Full name")


class UserCreate(UserBase):
    """Schema for creating a user."""
    password: str = Field(..., min_length=8, max_length=100,
                          description="Password (min 8 characters)")
    tenant_id: UUID = Field(..., description="Tenant ID")
    is_admin: bool = Field(False, description="Admin privileges")


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=255)
    password: Optional[str] = Field(None, min_length=8, max_length=100)
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None


class UserResponse(UserBase, BaseResponse):
    """Schema for user response."""
    tenant_id: UUID
    is_active: bool
    is_admin: bool

    model_config = ConfigDict(from_attributes=True)


# ===== Authentication Schemas =====

class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Data stored in JWT token."""
    user_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    email: Optional[str] = None


class LoginRequest(BaseModel):
    """Login request."""
    email: EmailStr
    password: str