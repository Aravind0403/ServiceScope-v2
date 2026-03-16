"""
Analysis Job Pydantic Schemas

Request/response models for analysis job operations.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from app.schemas.base import BaseResponse
from app.models.job import JobStatus


class AnalysisJobResponse(BaseResponse):
    """Schema for analysis job response."""
    repository_id: UUID
    status: JobStatus
    progress: float = Field(ge=0.0, le=100.0)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    result_summary: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)