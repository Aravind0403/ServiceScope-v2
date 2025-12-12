"""
Analysis Job Model

Tracks the progress and status of background analysis tasks.

Lifecycle:
1. Job created: status = QUEUED, progress = 0%
2. Celery picks up: status = RUNNING, progress = 10%
3. During analysis: progress updates (25%, 50%, 75%)
4. Complete: status = COMPLETED, progress = 100%
5. If error: status = FAILED, error_message set

Example:
    job = AnalysisJob(
        repository_id=repo.id,
        status=JobStatus.QUEUED
    )

    # Later in Celery task:
    job.status = JobStatus.RUNNING
    job.progress = 50.0
    job.started_at = datetime.utcnow()
"""

from sqlalchemy import Column, String, Float, Text, ForeignKey, Enum as SQLEnum, \
    DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.models.base import Base, UUIDMixin, TimestampMixin
import enum
from datetime import datetime


class JobStatus(str, enum.Enum):
    """
    Analysis job status.

    State transitions:
    QUEUED → RUNNING → COMPLETED
                 ↓
              FAILED
                 ↓
            CANCELLED (user cancels)
    """
    QUEUED = "queued"  # Waiting for Celery worker
    RUNNING = "running"  # Currently processing
    COMPLETED = "completed"  # Successfully finished
    FAILED = "failed"  # Error occurred
    CANCELLED = "cancelled"  # User cancelled


class AnalysisJob(Base, UUIDMixin, TimestampMixin):
    """
    Background analysis job for a repository.

    Why separate Job from Repository?
    - Repository can have multiple analysis runs
    - Track history (re-analyze after code changes)
    - Different branches can have separate jobs

    Progress tracking:
    - 0%: Job queued
    - 10%: Cloning repository
    - 30%: Extracting HTTP calls
    - 60%: LLM inference
    - 90%: Building Neo4j graph
    - 100%: Complete
    """
    __tablename__ = "analysis_jobs"

    # === Foreign Key ===
    repository_id = Column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Which repository this job analyzes"
    )

    # === Job Status ===
    status = Column(
        SQLEnum(JobStatus),
        default=JobStatus.QUEUED,
        nullable=False,
        index=True,  # Fast filtering: "show me all running jobs"
        comment="Current job state"
    )

    progress = Column(
        Float,
        default=0.0,
        nullable=False,
        comment="Completion percentage (0.0 to 100.0)"
    )

    # === Timing ===
    started_at = Column(
        DateTime(timezone=True),
        comment="When Celery worker started processing"
    )

    completed_at = Column(
        DateTime(timezone=True),
        comment="When job finished (success or failure)"
    )

    # === Error Handling ===
    error_message = Column(
        Text,
        comment="Error details if status=FAILED"
    )

    # === Results Summary ===
    result_summary = Column(
        JSONB,
        comment="JSON summary of results"
    )
    # Example result_summary:
    # {
    #   "services_found": 5,
    #   "api_calls_extracted": 23,
    #   "dependencies_inferred": 18,
    #   "neo4j_nodes_created": 5,
    #   "neo4j_edges_created": 18
    # }

    # === Relationships ===
    repository = relationship("Repository", back_populates="jobs")

    def __repr__(self):
        return f"<AnalysisJob {self.id} ({self.status.value}, {self.progress}%)>"

    @property
    def is_complete(self) -> bool:
        """Check if job has finished (success or failure)"""
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED,
                               JobStatus.CANCELLED)

    @property
    def is_active(self) -> bool:
        """Check if job is currently running"""
        return self.status in (JobStatus.QUEUED, JobStatus.RUNNING)

    @property
    def duration_seconds(self) -> float:
        """Calculate how long job took (or is taking)"""
        if not self.started_at:
            return 0.0

        end_time = self.completed_at or datetime.utcnow()
        delta = end_time - self.started_at
        return delta.total_seconds()

    def update_progress(self, progress: float, status: JobStatus = None):
        """
        Update job progress and optionally status.

        Args:
            progress: Percentage complete (0-100)
            status: New status (optional)

        Example:
            job.update_progress(25.0, JobStatus.RUNNING)
        """
        self.progress = min(100.0, max(0.0, progress))  # Clamp to 0-100
        if status:
            self.status = status

        # Auto-set timestamps
        if status == JobStatus.RUNNING and not self.started_at:
            self.started_at = datetime.utcnow()

        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            self.completed_at = datetime.utcnow()
            if status == JobStatus.COMPLETED:
                self.progress = 100.0

# Example usage in Celery task:
#
# from app.models.job import AnalysisJob, JobStatus
#
# @celery_app.task(bind=True)
# def analyze_repository_task(self, job_id: str):
#     # Load job from database
#     job = db.query(AnalysisJob).filter_by(id=job_id).first()
#
#     try:
#         # Update status
#         job.update_progress(10, JobStatus.RUNNING)
#         db.commit()
#
#         # Clone repo
#         clone_repository(job.repository.url)
#         job.update_progress(30)
#         db.commit()
#
#         # Extract calls
#         calls = extract_http_calls()
#         job.update_progress(60)
#         db.commit()
#
#         # Infer dependencies
#         dependencies = infer_dependencies(calls)
#         job.update_progress(90)
#         db.commit()
#
#         # Build graph
#         build_neo4j_graph(dependencies)
#
#         # Complete
#         job.result_summary = {
#             "services_found": 5,
#             "api_calls_extracted": len(calls),
#             "dependencies_inferred": len(dependencies)
#         }
#         job.update_progress(100, JobStatus.COMPLETED)
#         db.commit()
#
#     except Exception as e:
#         job.status = JobStatus.FAILED
#         job.error_message = str(e)
#         job.completed_at = datetime.utcnow()
#         db.commit()
#         raise