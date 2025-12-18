#!/usr/bin/env python3
"""
Load Existing Dependencies to Neo4j

This script loads all existing inferred dependencies from PostgreSQL
into Neo4j for graph visualization.

Usage:
    python scripts/load_to_neo4j_fixed.py
    python scripts/load_to_neo4j_fixed.py --clear
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Use sync SQLAlchemy directly
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db.Neo4j_session import neo4j_client
from app.models.api_call import ExtractedCall
from app.models.dependency import InferredDependency
import argparse

# Create sync engine and session
sync_engine = create_engine(settings.SYNC_DATABASE_URL)
SessionLocal = sessionmaker(bind=sync_engine)


def clear_neo4j():
    """Clear all data from Neo4j."""
    print("🗑️  Clearing Neo4j...")
    neo4j_client.clear_all()
    print("✅ Neo4j cleared")


def load_dependencies():
    """Load all dependencies from PostgreSQL to Neo4j."""
    db = SessionLocal()

    try:
        # Get all inferred dependencies
        dependencies = db.execute(select(InferredDependency)).scalars().all()

        if not dependencies:
            print("❌ No dependencies found in database")
            print("\n💡 Submit a repository first:")
            print("   1. Go to http://localhost:8000/docs")
            print("   2. Login and submit a repository")
            print("   3. Wait for analysis to complete")
            print("   4. Run this script again")
            return

        print(f"📊 Found {len(dependencies)} dependencies to load")

        # Track unique services
        services_created = set()
        edges_created = 0

        for dep in dependencies:
            # Get the associated call for URL and method
            call = db.execute(
                select(ExtractedCall).where(ExtractedCall.id == dep.extracted_call_id)
            ).scalar_one_or_none()

            if not call:
                continue

            # Create service nodes
            if dep.caller_service not in services_created:
                neo4j_client.create_service_node(dep.caller_service)
                services_created.add(dep.caller_service)
                print(f"   ✅ Created service: {dep.caller_service}")

            if dep.callee_service not in services_created:
                neo4j_client.create_service_node(dep.callee_service)
                services_created.add(dep.callee_service)
                print(f"   ✅ Created service: {dep.callee_service}")

            # Create dependency edge
            neo4j_client.create_dependency_edge(
                caller=dep.caller_service,
                callee=dep.callee_service,
                method=call.method,
                url=call.url,
                confidence=dep.confidence
            )
            edges_created += 1
            print(f"   ✅ Created edge: {dep.caller_service} → {dep.callee_service}")

        print("\n" + "=" * 60)
        print("🎉 LOAD COMPLETE!")
        print("=" * 60)
        print(f"📊 Services created: {len(services_created)}")
        print(f"🔗 Dependencies created: {edges_created}")
        print("\n🌐 Open Neo4j Browser:")
        print("   URL: http://localhost:7474")
        print("   (No authentication required)")
        print("\n💡 Try this query:")
        print("   MATCH (n:Service)-[r:CALLS]->(m:Service)")
        print("   RETURN n, r, m")

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Load dependencies to Neo4j")
    parser.add_argument("--clear", action="store_true",
                        help="Clear Neo4j before loading")
    args = parser.parse_args()

    print("🚀 Loading Dependencies to Neo4j")
    print("=" * 60)

    # Test connection
    try:
        neo4j_client.connect()
        print("✅ Connected to Neo4j")
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        print("\n💡 Make sure Neo4j is running:")
        print("   docker-compose up -d neo4j")
        print("   # Wait 30 seconds")
        return

    # Clear if requested
    if args.clear:
        clear_neo4j()

    # Load data
    load_dependencies()


if __name__ == "__main__":
    main()