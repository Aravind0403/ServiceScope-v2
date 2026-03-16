"""
Database Session Management

Async PostgreSQL connection using SQLAlchemy 2.0

Usage:
    from app.db.session import get_db

    @app.get("/tenants")
    async def list_tenants(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(Tenant))
        return result.scalars().all()
"""
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.config import settings

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # Log SQL queries in debug mode
    future=True,
    pool_pre_ping=True,  # Verify connections before using
    poolclass=NullPool if settings.DEBUG else None  # No pooling in tests
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
    autocommit=False,
    autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession | Any, Any]:
    """
    Dependency for FastAPI endpoints.

    Usage:
        @app.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Item))
            return result.scalars().all()

    Automatically commits on success, rolls back on error.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """
    Initialize database - create all tables.

    ⚠️  For development only! Use Alembic in production.

    Usage:
        from app.db.session import init_db
        await init_db()
    """
    from app.models.base import Base

    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections (for shutdown)."""
    await engine.dispose()