"""
ServiceScope FastAPI Application

Main application entry point with FastAPI setup, middleware, and lifecycle events.

Usage:
    uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

from app.config import settings
from app.db import init_db, close_db, init_neo4j, close_neo4j


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager."""
    print("🚀 Starting ServiceScope API...")

    # Initialize Neo4j connection (optional)
    try:
        await init_neo4j()
    except Exception as e:
        print(f"⚠️  Neo4j not available: {e}")
        print("   Continuing without Neo4j (graph features disabled)")

    print("✅ Database connections initialized")

    yield

    print("🛑 Shutting down ServiceScope API...")
    await close_db()
    try:
        await close_neo4j()
    except:
        pass
    print("✅ Database connections closed")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered microservice dependency mapper using LLMs and graph databases",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/", tags=["Health"])
async def root():
    """
    Root endpoint - health check.

    Returns basic API information.
    """
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Detailed health check endpoint.

    Checks status of all services.
    """
    from app.db import engine, neo4j_client

    health = {
        "status": "healthy",
        "services": {}
    }

    # Check PostgreSQL
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        health["services"]["postgresql"] = "healthy"
    except Exception as e:
        health["services"]["postgresql"] = f"unhealthy: {str(e)}"
        health["status"] = "degraded"

    # Check Neo4j
    try:
        neo4j_client.execute_query("RETURN 1")
        health["services"]["neo4j"] = "healthy"
    except Exception as e:
        health["services"]["neo4j"] = f"unhealthy: {str(e)}"
        health["status"] = "degraded"

    return health


# Import and include routers
from app.routers import auth, tenant, repositories, jobs

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(tenant.router, prefix="/api/v1/tenants", tags=["Tenants"])
app.include_router(repositories.router, prefix="/api/v1/repositories", tags=["Repositories"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Analysis Jobs"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )