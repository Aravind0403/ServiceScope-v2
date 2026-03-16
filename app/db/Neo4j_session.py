"""
Neo4j Connection Manager

Synchronous Neo4j driver for graph operations.

All Service nodes and CALLS edges are scoped by tenant_id and repository_id so
that data from different tenants or different repositories never bleeds into
each other's queries.

Usage:
    from app.db.neo4j_session import get_neo4j, neo4j_client

    # Direct usage
    with neo4j_client.session() as session:
        result = session.run("MATCH (n) RETURN n LIMIT 10")

    # In FastAPI
    driver = get_neo4j()
    with driver.session() as session:
        result = session.run(query, params)
"""

from neo4j import GraphDatabase
from app.config import settings
from typing import Optional


class Neo4jClient:
    """
    Neo4j connection manager.

    Maintains a single driver instance for the application.
    """

    def __init__(self):
        self._driver: Optional[GraphDatabase.driver] = None

    def connect(self):
        """Establish connection to Neo4j."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
                max_connection_lifetime=3600,  # 1 hour
                max_connection_pool_size=50,
                connection_timeout=30
            )
            # Verify connectivity
            self._driver.verify_connectivity()
            self._ensure_indexes()

    def _ensure_indexes(self):
        """Create composite indexes for tenant-scoped queries."""
        indexes = [
            "CREATE INDEX service_tenant_idx IF NOT EXISTS FOR (s:Service) ON (s.name, s.tenant_id)",
            "CREATE INDEX service_repo_idx IF NOT EXISTS FOR (s:Service) ON (s.repository_id)",
        ]
        with self.session() as session:
            for idx in indexes:
                try:
                    session.run(idx)
                except Exception:
                    pass  # Index may already exist or not be supported on this version

    def close(self):
        """Close Neo4j connection."""
        if self._driver:
            self._driver.close()
            self._driver = None

    @property
    def driver(self):
        """Get Neo4j driver instance."""
        if self._driver is None:
            self.connect()
        return self._driver

    def session(self):
        """Create a new Neo4j session."""
        return self.driver.session()

    def execute_query(self, query: str, parameters: dict = None):
        """
        Execute a Cypher query.

        Args:
            query: Cypher query string
            parameters: Query parameters

        Returns:
            Query result
        """
        with self.session() as session:
            result = session.run(query, parameters or {})
            return [record for record in result]

    def create_service_node(
        self,
        service_name: str,
        tenant_id: str,
        repository_id: str,
        properties: dict = None,
    ):
        """
        Create or update a service node scoped to a tenant and repository.

        Args:
            service_name: Name of the service
            tenant_id: Tenant UUID string
            repository_id: Repository UUID string
            properties: Additional properties

        Example:
            neo4j_client.create_service_node(
                "payment_service",
                tenant_id="abc123",
                repository_id="repo456",
            )
        """
        props = properties or {}
        props.update({
            "name": service_name,
            "tenant_id": str(tenant_id),
            "repository_id": str(repository_id),
        })

        query = """
        MERGE (s:Service {name: $name, tenant_id: $tenant_id, repository_id: $repository_id})
        SET s += $properties
        RETURN s
        """
        return self.execute_query(query, {
            "name": service_name,
            "tenant_id": str(tenant_id),
            "repository_id": str(repository_id),
            "properties": props,
        })

    def create_dependency_edge(
        self,
        caller: str,
        callee: str,
        method: str,
        url: str,
        tenant_id: str,
        repository_id: str,
        confidence: float = None,
    ):
        """
        Create a CALLS relationship between services scoped to a tenant/repo.

        Args:
            caller: Calling service name
            callee: Called service name
            method: HTTP method
            url: Full URL
            tenant_id: Tenant UUID string
            repository_id: Repository UUID string
            confidence: LLM confidence score

        Example:
            neo4j_client.create_dependency_edge(
                "order_service", "payment_service",
                "POST", "http://payment/charge",
                tenant_id="abc", repository_id="repo1", confidence=0.95,
            )
        """
        query = """
        MERGE (caller:Service {name: $caller, tenant_id: $tenant_id, repository_id: $repository_id})
        MERGE (callee:Service {name: $callee, tenant_id: $tenant_id, repository_id: $repository_id})
        MERGE (caller)-[r:CALLS {url: $url, tenant_id: $tenant_id}]->(callee)
        SET r.method = $method,
            r.confidence = $confidence,
            r.repository_id = $repository_id,
            r.updated_at = datetime()
        RETURN caller, r, callee
        """
        return self.execute_query(query, {
            "caller": caller,
            "callee": callee,
            "method": method,
            "url": url,
            "tenant_id": str(tenant_id),
            "repository_id": str(repository_id),
            "confidence": confidence,
        })

    def get_service_dependencies(self, service_name: str, tenant_id: str):
        """
        Get all services that a service depends on, scoped to a tenant.

        Args:
            service_name: Service to query
            tenant_id: Tenant UUID string

        Returns:
            List of services this service calls
        """
        query = """
        MATCH (s:Service {name: $name, tenant_id: $tenant_id})-[r:CALLS]->(target:Service)
        WHERE target.tenant_id = $tenant_id
        RETURN target.name as service, r.method as method, r.url as url,
               r.confidence as confidence, r.repository_id as repository_id
        """
        return self.execute_query(query, {"name": service_name, "tenant_id": str(tenant_id)})

    def get_repository_graph(self, repository_id: str, tenant_id: str):
        """
        Get the full dependency graph for a repository.

        Args:
            repository_id: Repository UUID string
            tenant_id: Tenant UUID string

        Returns:
            List of (caller, relationship, callee) records
        """
        query = """
        MATCH (caller:Service {repository_id: $repository_id, tenant_id: $tenant_id})
              -[r:CALLS]->
              (callee:Service {repository_id: $repository_id, tenant_id: $tenant_id})
        RETURN caller.name as caller, callee.name as callee,
               r.method as method, r.url as url, r.confidence as confidence
        """
        return self.execute_query(query, {
            "repository_id": str(repository_id),
            "tenant_id": str(tenant_id),
        })

    def clear_repository(self, repository_id: str, tenant_id: str):
        """
        Delete all nodes and edges for a specific repository (for re-analysis).

        Args:
            repository_id: Repository UUID string
            tenant_id: Tenant UUID string
        """
        query = """
        MATCH (s:Service {repository_id: $repository_id, tenant_id: $tenant_id})
        DETACH DELETE s
        """
        return self.execute_query(query, {
            "repository_id": str(repository_id),
            "tenant_id": str(tenant_id),
        })

    def clear_all(self):
        """
        ⚠️  Delete all nodes and relationships.
        Use only in development/testing!
        """
        query = "MATCH (n) DETACH DELETE n"
        return self.execute_query(query)


# Global Neo4j client instance
neo4j_client = Neo4jClient()


def get_neo4j():
    """
    Dependency for FastAPI endpoints.

    Usage:
        @app.get("/graph")
        def get_graph(neo4j = Depends(get_neo4j)):
            with neo4j.session() as session:
                result = session.run("MATCH (n) RETURN n")
    """
    return neo4j_client.driver


async def init_neo4j():
    """Initialize Neo4j connection on startup."""
    neo4j_client.connect()
    print("✅ Neo4j connected")


async def close_neo4j():
    """Close Neo4j connection on shutdown."""
    neo4j_client.close()
    print("✅ Neo4j closed")
