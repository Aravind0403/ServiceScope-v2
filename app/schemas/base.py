"""
Base Pydantic Schemas

Common base classes for request/response models.
"""

from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional
from uuid import UUID


class TimestampSchema(BaseModel):
    """Schema with timestamps."""
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UUIDSchema(BaseModel):
    """Schema with UUID primary key."""
    id: UUID

    model_config = ConfigDict(from_attributes=True)


class BaseResponse(UUIDSchema, TimestampSchema):
    """
    Base response schema with id and timestamps.

    Inherit from this for most response models.
    """
    pass