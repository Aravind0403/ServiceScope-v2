"""
Repository Model

Represents a Git repository submitted for dependency analysis.

Lifecycle:
1. User submits: status = PENDING
2. Celery clones: status = CLONING
3. Extract calls: status = ANALYZING
4. Complete: status = COMPLETED
5. Error: status = FAILED

Example repositories:
- https://github.com/user/microservice-a
- https://github.com/company/api-gateway
- https://gitlab.com/team/payment-service
"""

from sqlalchemy import Column, String, Text, Integer, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models.base import Base, UUIDMixin, TimestampMixin
import enum


class RepositoryStatus(str, enum.Enum):
    """
    Repository analysis status.

    State machine:
    PENDING → CLONING → ANALYZING → COMPLETED
                  ↓          ↓
                FAILED    FAILED
    """
    PENDING = "pending"  # Just created, not started
    CLONING = "cloning"  # Git clone in progress
    ANALYZING = "analyzing"  # Extraction + inference running
    COMPLETED = "completed"  # Successfully analyzed
    FAILED = "failed"  # Error occurred


class Repository(Base, UUIDMixin, TimestampMixin):
    """
    A Git repository to analyze for service dependencies.

    Table structure:
    - id: UUID (primary key)
    - tenant_id: UUID (which company owns this)
    - url: String (https://github.com/user/repo)
    - status: Enum (PENDING, CLONING, etc.)
    - created_at: Timestamp
    - updated_at: Timestamp
    """
    __tablename__ = "repositories"

    # === Ownership ===
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Which tenant owns this repository"
    )

    # === Repository Info ===
    url = Column(
        String(512),
        nullable=False,
        comment="Git URL (https://github.com/user/repo)"
    )

    name = Column(
        String(255),
        comment="Human-readable name (extracted from URL)"
    )

    branch = Column(
        String(100),
        default="main",
        comment="Git branch to analyze (main, master, develop)"
    )

    # === Analysis Status ===
    status = Column(
        SQLEnum(RepositoryStatus),
        default=RepositoryStatus.PENDING,
        nullable=False,
        index=True,  # Fast filtering by status
        comment="Current analysis state"
    )

    error_message = Column(
        Text,
        comment="Error details if status=FAILED"
    )

    # === Metadata (populated during analysis) ===
    clone_path = Column(
        String(512),
        comment="Local filesystem path where repo is cloned"
    )

    commit_hash = Column(
        String(40),  # Git SHA-1 = 40 hex chars
        comment="Git commit that was analyzed"
    )

    file_count = Column(
        Integer,
        comment="Number of Python files found"
    )

    # === Relationships ===

    # Many-to-one: Repository belongs to one tenant
    tenant = relationship("Tenant", back_populates="repositories")

    # One-to-many: Repository has many analysis jobs
    jobs = relationship(
        "AnalysisJob",
        back_populates="repository",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )

    # One-to-many: Repository has many extracted API calls
    api_calls = relationship(
        "ExtractedCall",
        back_populates="repository",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )

    def __repr__(self):
        return f"<Repository {self.name or self.url} ({self.status.value})>"

    @property
    def is_complete(self) -> bool:
        """Check if analysis is done (success or failure)"""
        return self.status in (RepositoryStatus.COMPLETED, RepositoryStatus.FAILED)

    @property
    def is_processing(self) -> bool:
        """Check if analysis is in progress"""
        return self.status in (RepositoryStatus.CLONING, RepositoryStatus.ANALYZING)

    def get_latest_job(self):
        """Get the most recent analysis job"""
        return self.jobs.order_by(self.jobs.created_at.desc()).first()

# Example usage:
#
# # Create repository
# repo = Repository(
#     tenant_id=tenant.id,
#     url="https://github.com/user/my-microservice",
#     name="my-microservice",
#     branch="main",
#     status=RepositoryStatus.PENDING
# )
#
# # Later, update status
# repo.status = RepositoryStatus.CLONING
# repo.clone_path = "/tmp/repos/abc-123"
#
# # Check status
# if repo.is_complete:
#     print("Analysis done!")