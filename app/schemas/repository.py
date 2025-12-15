"""
Repository Pydantic Schemas

Request/response models for Repository operations.
"""

from pydantic import BaseModel, Field, HttpUrl, ConfigDict
from typing import Optional
from uuid import UUID

from app.schemas.base import BaseResponse
from app.models.repository import RepositoryStatus


class RepositoryBase(BaseModel):
    """Base repository fields."""
    url: str = Field(..., description="Git repository URL")
    name: Optional[str] = Field(None, max_length=255, description="Repository name")
    branch: str = Field("main", max_length=100, description="Git branch to analyze")


class RepositoryCreate(RepositoryBase):
    """Schema for creating a repository."""
    tenant_id: UUID = Field(..., description="Tenant ID")


class RepositoryUpdate(BaseModel):
    """Schema for updating a repository."""
    name: Optional[str] = Field(None, max_length=255)
    branch: Optional[str] = Field(None, max_length=100)
    status: Optional[RepositoryStatus] = None


class RepositoryResponse(RepositoryBase, BaseResponse):
    """Schema for repository response."""
    tenant_id: UUID
    status: RepositoryStatus
    error_message: Optional[str] = None
    clone_path: Optional[str] = None
    commit_hash: Optional[str] = None
    file_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class RepositoryListResponse(BaseModel):
    """Schema for paginated repository list."""
    items: list[RepositoryResponse]
    total: int
    page: int
    page_size: int