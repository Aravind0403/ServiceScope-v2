"""Analysis Job Model"""

from sqlalchemy import Column, String, Float, Text, ForeignKey, Enum as SQLEnum, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.models.base import Base, UUIDMixin, TimestampMixin


class JobStatus(str, enum.Enum):
    """Analysis job status."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisJob(Base, UUIDMixin, TimestampMixin):
    """Background analysis job for a repository."""
    __tablename__ = "analysis_jobs"

    repository_id = Column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    status = Column(
        SQLEnum(JobStatus),
        default=JobStatus.QUEUED,
        nullable=False,
        index=True
    )

    progress = Column(Float, default=0.0, nullable=False)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    error_message = Column(Text)
    result_summary = Column(JSONB)

    repository = relationship("Repository", back_populates="jobs")

    def update_progress(self, progress: float, status: JobStatus = None):
        """Update job progress."""
        self.progress = min(100.0, max(0.0, progress))
        if status:
            self.status = status
        if status == JobStatus.RUNNING and not self.started_at:
            self.started_at = datetime.utcnow()
        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            self.completed_at = datetime.utcnow()