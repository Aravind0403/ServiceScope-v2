"""
Base Models

This module provides base classes that other models inherit from.
Common patterns like UUID primary keys and timestamps are defined here.

Why use base classes?
- DRY (Don't Repeat Yourself)
- Every model gets id, created_at, updated_at automatically
- Consistent behavior across all tables
"""

from sqlalchemy import Column, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
import uuid

# This is the base class ALL models inherit from
Base = declarative_base()


class UUIDMixin:
    """
    Provides a UUID primary key for models.

    Why UUID instead of integer?
    - Globally unique (can merge databases)
    - Non-sequential (harder to guess/enumerate)
    - Better for distributed systems
    - URL-safe

    Example:
        class User(Base, UUIDMixin):
            pass

        # Creates table with: id UUID PRIMARY KEY
    """
    id = Column(
        UUID(as_uuid=True),  # Store as native UUID type (not string)
        primary_key=True,
        default=uuid.uuid4,  # Auto-generate on insert
        nullable=False
    )


class TimestampMixin:
    """
    Provides created_at and updated_at timestamps.

    Why timestamps?
    - Audit trail (when was this created/modified?)
    - Debugging (find recent changes)
    - Analytics (user growth over time)

    Features:
    - created_at: Set once on insert, never changes
    - updated_at: Auto-updates on every modification
    - Timezone-aware (always UTC)

    Example:
        class Post(Base, TimestampMixin):
            pass

        # Creates table with:
        # created_at TIMESTAMP NOT NULL DEFAULT NOW()
        # updated_at TIMESTAMP NOT NULL DEFAULT NOW() ON UPDATE NOW()
    """
    created_at = Column(
        DateTime(timezone=True),  # Store with timezone info
        server_default=func.now(),  # Database sets this, not Python
        nullable=False
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),  # Auto-update on modifications
        nullable=False
    )

# Example usage in other models:
#
# class Repository(Base, UUIDMixin, TimestampMixin):
#     __tablename__ = "repositories"
#     name = Column(String(255))
#
# This creates a table with:
# - id (UUID, primary key)
# - name (string)
# - created_at (timestamp)
# - updated_at (timestamp)