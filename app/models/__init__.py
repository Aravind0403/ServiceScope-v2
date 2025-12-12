"""
Database Models

All SQLAlchemy ORM models for ServiceScope.

Import order is important:
1. Base classes first (base.py)
2. Independent models (tenant, user)
3. Dependent models (repository, job, api_call, dependency)

Usage:
    from app.models import Tenant, User, Repository, AnalysisJob

    tenant = Tenant(name="Acme Corp")
    user = User(tenant_id=tenant.id, email="admin@acme.com")
"""

# Base classes
from app.models.base import Base, UUIDMixin, TimestampMixin

# Independent models (no foreign keys)
from app.models.tenant import Tenant, User

# Repository models (depends on Tenant)
from app.models.repository import Repository, RepositoryStatus

# Job models (depends on Repository)
from app.models.job import AnalysisJob, JobStatus

# Call models (depends on Repository)
from app.models.api_call import ExtractedCall

# Dependency models (depends on ExtractedCall)
from app.models.dependency import InferredDependency

# Export everything for easy importing
__all__ = [
    # Base
    "Base",
    "UUIDMixin",
    "TimestampMixin",

    # Tenant & Users
    "Tenant",
    "User",

    # Repository
    "Repository",
    "RepositoryStatus",

    # Jobs
    "AnalysisJob",
    "JobStatus",

    # API Calls
    "ExtractedCall",

    # Dependencies
    "InferredDependency",
]