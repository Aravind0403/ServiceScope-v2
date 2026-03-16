"""
Tenant & User Models

Multi-tenancy Architecture:
- Tenant = Organization/Company (e.g., "Acme Corp")
- User = Person within a tenant (e.g., john@acme.com)

Why multi-tenant?
- SaaS requirement: Each company has isolated data
- Revenue model: Charge per tenant
- Security: Tenant A can't see Tenant B's data

Data Isolation Strategy:
- Every table has tenant_id column
- All queries filter by tenant_id
- Users belong to exactly one tenant
"""

from sqlalchemy import Column, String, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models.base import Base, UUIDMixin, TimestampMixin


class Tenant(Base, UUIDMixin, TimestampMixin):
    """
    Organization/Company that uses ServiceScope.

    Example tenants:
    - "Acme Corporation" (analyzing 50 repos)
    - "Startup XYZ" (analyzing 5 repos)
    - "Enterprise Inc" (analyzing 200 repos)

    Billing model:
    - Free tier: 10 repos, 60 req/min
    - Pro tier: 100 repos, 600 req/min
    - Enterprise: Unlimited repos, custom rate limits
    """
    __tablename__ = "tenants"

    # Basic info
    name = Column(
        String(255),
        nullable=False,
        comment="Organization name (e.g., 'Acme Corp')"
    )

    # API authentication
    api_key = Column(
        String(64),  # SHA-256 hash = 64 hex chars
        unique=True,
        nullable=False,
        index=True,  # Fast lookup by API key
        comment="API key for programmatic access"
    )

    # Status
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="False = suspended (billing issue, TOS violation)"
    )

    # Rate limiting (prevent abuse)
    rate_limit_rpm = Column(
        Integer,
        default=60,  # Requests per minute
        nullable=False,
        comment="Max API requests per minute"
    )

    # Resource quotas
    max_repositories = Column(
        Integer,
        default=10,
        nullable=False,
        comment="Max repos tenant can analyze"
    )

    # Relationships (one-to-many)
    # A tenant has many repositories
    repositories = relationship(
        "Repository",
        back_populates="tenant",
        cascade="all, delete-orphan",  # Delete repos when tenant deleted
        lazy="dynamic"  # Don't load all repos automatically
    )

    # A tenant has many users
    users = relationship(
        "User",
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )

    def __repr__(self):
        return f"<Tenant {self.name} (active={self.is_active})>"

    def can_create_repository(self) -> bool:
        """Check if tenant can create more repositories"""
        current_count = self.repositories.count()
        return current_count < self.max_repositories


class User(Base, UUIDMixin, TimestampMixin):
    """
    Individual user within a tenant.

    Example users:
    - john@acme.com (admin at Acme Corp)
    - jane@acme.com (developer at Acme Corp)
    - admin@startup.io (admin at Startup XYZ)

    Authentication flow:
    1. User logs in with email + password
    2. System verifies password hash
    3. Returns JWT token with user_id + tenant_id
    4. All subsequent requests include JWT
    """
    __tablename__ = "users"

    # Foreign key to tenant
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),  # Delete user if tenant deleted
        nullable=False,
        index=True,  # Fast filtering by tenant
        comment="Which organization this user belongs to"
    )

    # Authentication
    email = Column(
        String(255),
        unique=True,  # No duplicate emails across ALL tenants
        nullable=False,
        index=True,  # Fast login lookup
        comment="User's email (used for login)"
    )

    hashed_password = Column(
        String(255),
        nullable=False,
        comment="bcrypt hash of password (never store plaintext!)"
    )

    # Profile
    full_name = Column(
        String(255),
        comment="Display name (e.g., 'John Doe')"
    )

    # Status
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="False = account disabled"
    )

    # Permissions
    is_admin = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="True = can manage tenant settings"
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="users")

    def __repr__(self):
        return f"<User {self.email} (tenant={self.tenant_id})>"

    def verify_password(self, password: str) -> bool:
        """
        Check if provided password matches stored hash.

        Uses bcrypt (slow by design to prevent brute force).

        Args:
            password: Plaintext password from login form

        Returns:
            True if password matches, False otherwise
        """
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return pwd_context.verify(password, self.hashed_password)

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a plaintext password for storage.

        Args:
            password: Plaintext password

        Returns:
            Bcrypt hash string
        """
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return pwd_context.hash(password)

# Example usage:
#
# # Create tenant
# tenant = Tenant(
#     name="Acme Corp",
#     api_key="sk_live_abc123...",
#     rate_limit_rpm=100,
#     max_repositories=50
# )
#
# # Create user
# user = User(
#     tenant_id=tenant.id,
#     email="john@acme.com",
#     hashed_password=User.hash_password("SecurePassword123!"),
#     full_name="John Doe",
#     is_admin=True
# )
#
# # Check password
# if user.verify_password("SecurePassword123!"):
#     print("Login successful!")