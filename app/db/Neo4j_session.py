"""
Neo4j Connection Manager

Synchronous Neo4j driver for graph operations.

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

        Example:
            result = neo4j_client.execute_query(
                "MATCH (n:Service {name: $name}) RETURN n",
                {"name": "payment_service"}
            )
        """
        with self.session() as session:
            result = session.run(query, parameters or {})
            return [record for record in result]

    def create_service_node(self, service_name: str, properties: dict = None):
        """
        Create or update a service node.

        Args:
            service_name: Name of the service
            properties: Additional properties

        Example:
            neo4j_client.create_service_node(
                "payment_service",
                {"version": "1.0", "language": "python"}
            )
        """
        props = properties or {}
        props["name"] = service_name

        query = """
        MERGE (s:Service {name: $name})
        SET s += $properties
        RETURN s
        """
        return self.execute_query(query, {"name": service_name, "properties": props})

    def create_dependency_edge(
            self,
            caller: str,
            callee: str,
            method: str,
            url: str,
            confidence: float = None
    ):
        """
        Create a CALLS relationship between services.

        Args:
            caller: Calling service name
            callee: Called service name
            method: HTTP method
            url: Full URL
            confidence: LLM confidence score

        Example:
            neo4j_client.create_dependency_edge(
                "order_service",
                "payment_service",
                "POST",
                "http://payment/charge",
                0.95
            )
        """
        query = """
        MERGE (caller:Service {name: $caller})
        MERGE (callee:Service {name: $callee})
        MERGE (caller)-[r:CALLS {url: $url}]->(callee)
        SET r.method = $method,
            r.confidence = $confidence,
            r.updated_at = datetime()
        RETURN caller, r, callee
        """
        return self.execute_query(query, {
            "caller": caller,
            "callee": callee,
            "method": method,
            "url": url,
            "confidence": confidence
        })

    def get_service_dependencies(self, service_name: str):
        """
        Get all services that a service depends on.

        Args:
            service_name: Service to query

        Returns:
            List of services this service calls
        """
        query = """
        MATCH (s:Service {name: $name})-[r:CALLS]->(target:Service)
        RETURN target.name as service, r.method as method, r.url as url
        """
        return self.execute_query(query, {"name": service_name})

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