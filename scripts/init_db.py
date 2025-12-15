#!/usr/bin/env python3
"""
Database Initialization Script

Run migrations and verify connections.

Usage:
    python scripts/init_db.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.db import engine, init_db, neo4j_client
from app.config import settings


async def test_postgres():
    """Test PostgreSQL connection."""
    print("🔍 Testing PostgreSQL connection...")
    try:
        async with engine.connect() as conn:
            result = await conn.execute("SELECT 1")
            print("✅ PostgreSQL connected successfully")
            return True
    except Exception as e:
        print(f"❌ PostgreSQL connection failed: {e}")
        return False


def test_neo4j():
    """Test Neo4j connection."""
    print("🔍 Testing Neo4j connection...")
    try:
        neo4j_client.connect()
        result = neo4j_client.execute_query("RETURN 1 as test")
        print("✅ Neo4j connected successfully")
        return True
    except Exception as e:
        print(f"❌ Neo4j connection failed: {e}")
        return False


async def main():
    """Initialize database."""
    print("=" * 60)
    print("🚀 ServiceScope - Database Initialization")
    print("=" * 60)

    # Test connections
    print("\n1️⃣  Testing database connections...\n")

    postgres_ok = await test_postgres()
    neo4j_ok = test_neo4j()

    if not postgres_ok:
        print("\n❌ PostgreSQL is not available. Please start it:")
        print("   docker-compose up -d postgres")
        sys.exit(1)

    if not neo4j_ok:
        print("\n❌ Neo4j is not available. Please start it:")
        print("   docker-compose up -d neo4j")
        sys.exit(1)

    # Run migrations
    print("\n2️⃣  Running database migrations...\n")
    print("⚠️  Note: Run 'alembic upgrade head' manually")
    print("   (Alembic doesn't work well in async context)")

    # Done
    print("\n" + "=" * 60)
    print("✅ Database initialization complete!")
    print("=" * 60)
    print("\n📝 Next steps:")
    print("   1. Run migrations: alembic upgrade head")
    print("   2. Start API server: uvicorn app.main:app --reload")
    print("   3. Visit docs: http://localhost:8000/docs\n")


if __name__ == "__main__":
    asyncio.run(main())