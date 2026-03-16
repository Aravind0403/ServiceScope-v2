"""
Pydantic Schemas

Request/response models for API endpoints.
"""

from app.schemas.base import BaseResponse, TimestampSchema, UUIDSchema
from app.schemas.tenant import (
    TenantCreate,
    TenantUpdate,
    TenantResponse,
    UserCreate,
    UserUpdate,
    UserResponse,
    Token,
    TokenData,
    LoginRequest,
)
from app.schemas.repository import (
    RepositoryCreate,
    RepositoryUpdate,
    RepositoryResponse,
    RepositoryListResponse,
)

__all__ = [
    # Base
    "BaseResponse",
    "TimestampSchema",
    "UUIDSchema",

    # Tenant & User
    "TenantCreate",
    "TenantUpdate",
    "TenantResponse",
    "UserCreate",
    "UserUpdate",
    "UserResponse",

    # Auth
    "Token",
    "TokenData",
    "LoginRequest",

    # Repository
    "RepositoryCreate",
    "RepositoryUpdate",
    "RepositoryResponse",
    "RepositoryListResponse",
]