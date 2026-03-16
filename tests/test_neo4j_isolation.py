"""
Tests for Neo4j multi-tenant and multi-repository isolation.

These tests use a mock Neo4jClient to verify that all queries include
tenant_id and repository_id, ensuring no cross-tenant data leakage.

For integration tests against a live Neo4j instance, set the
INTEGRATION_NEO4J environment variable and ensure Neo4j is running.
"""

import os
import pytest
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

from app.db.Neo4j_session import Neo4jClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_client() -> Neo4jClient:
    """Return a Neo4jClient with a mocked driver (no real connection needed)."""
    client = Neo4jClient()
    client._driver = MagicMock()

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter([]))
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.run.return_value = mock_result

    client._driver.session.return_value = mock_session
    return client, mock_session


# ---------------------------------------------------------------------------
# create_service_node — tenant/repo in MERGE key
# ---------------------------------------------------------------------------

class TestCreateServiceNode:
    def test_merge_includes_tenant_id(self):
        client, session = make_client()
        tenant_id = str(uuid4())
        repo_id = str(uuid4())

        client.create_service_node("payment_service", tenant_id=tenant_id, repository_id=repo_id)

        query, params = session.run.call_args[0][0], session.run.call_args[0][1]
        assert "tenant_id" in query
        assert params["tenant_id"] == tenant_id

    def test_merge_includes_repository_id(self):
        client, session = make_client()
        tenant_id = str(uuid4())
        repo_id = str(uuid4())

        client.create_service_node("order_service", tenant_id=tenant_id, repository_id=repo_id)

        query, params = session.run.call_args[0][0], session.run.call_args[0][1]
        assert "repository_id" in query
        assert params["repository_id"] == repo_id

    def test_different_tenants_produce_different_params(self):
        client_a, session_a = make_client()
        client_b, session_b = make_client()

        t_a, t_b = str(uuid4()), str(uuid4())
        repo = str(uuid4())

        client_a.create_service_node("svc", tenant_id=t_a, repository_id=repo)
        client_b.create_service_node("svc", tenant_id=t_b, repository_id=repo)

        params_a = session_a.run.call_args[0][1]
        params_b = session_b.run.call_args[0][1]
        assert params_a["tenant_id"] != params_b["tenant_id"]


# ---------------------------------------------------------------------------
# create_dependency_edge — tenant/repo in MERGE + SET
# ---------------------------------------------------------------------------

class TestCreateDependencyEdge:
    def test_edge_includes_tenant_id(self):
        client, session = make_client()
        tenant_id = str(uuid4())
        repo_id = str(uuid4())

        client.create_dependency_edge(
            "order_service", "payment_service",
            "POST", "http://payment/charge",
            tenant_id=tenant_id, repository_id=repo_id, confidence=0.9,
        )

        query, params = session.run.call_args[0][0], session.run.call_args[0][1]
        assert "tenant_id" in query
        assert params["tenant_id"] == tenant_id

    def test_edge_includes_repository_id(self):
        client, session = make_client()
        tenant_id = str(uuid4())
        repo_id = str(uuid4())

        client.create_dependency_edge(
            "a", "b", "GET", "http://b/api",
            tenant_id=tenant_id, repository_id=repo_id,
        )

        params = session.run.call_args[0][1]
        assert params["repository_id"] == repo_id

    def test_confidence_passed_through(self):
        client, session = make_client()
        client.create_dependency_edge(
            "a", "b", "GET", "http://b/api",
            tenant_id=str(uuid4()), repository_id=str(uuid4()), confidence=0.87,
        )
        params = session.run.call_args[0][1]
        assert abs(params["confidence"] - 0.87) < 0.001


# ---------------------------------------------------------------------------
# get_service_dependencies — filtered by tenant_id
# ---------------------------------------------------------------------------

class TestGetServiceDependencies:
    def test_query_filters_by_tenant(self):
        client, session = make_client()
        tenant_id = str(uuid4())

        client.get_service_dependencies("order_service", tenant_id=tenant_id)

        query, params = session.run.call_args[0][0], session.run.call_args[0][1]
        assert "tenant_id" in query
        assert params["tenant_id"] == tenant_id

    def test_different_tenants_use_different_ids(self):
        client, session = make_client()
        t_a = str(uuid4())
        t_b = str(uuid4())

        client.get_service_dependencies("svc", tenant_id=t_a)
        params_a = session.run.call_args[0][1].copy()

        client.get_service_dependencies("svc", tenant_id=t_b)
        params_b = session.run.call_args[0][1].copy()

        assert params_a["tenant_id"] != params_b["tenant_id"]


# ---------------------------------------------------------------------------
# get_repository_graph — scoped to both tenant and repo
# ---------------------------------------------------------------------------

class TestGetRepositoryGraph:
    def test_query_filters_by_both_ids(self):
        client, session = make_client()
        tenant_id = str(uuid4())
        repo_id = str(uuid4())

        client.get_repository_graph(repository_id=repo_id, tenant_id=tenant_id)

        query, params = session.run.call_args[0][0], session.run.call_args[0][1]
        assert "repository_id" in query
        assert "tenant_id" in query
        assert params["repository_id"] == repo_id
        assert params["tenant_id"] == tenant_id


# ---------------------------------------------------------------------------
# clear_repository — only deletes within tenant/repo scope
# ---------------------------------------------------------------------------

class TestClearRepository:
    def test_does_not_use_match_all(self):
        client, session = make_client()
        repo_id = str(uuid4())
        tenant_id = str(uuid4())

        client.clear_repository(repository_id=repo_id, tenant_id=tenant_id)

        query = session.run.call_args[0][0]
        # Ensure it's NOT wiping all nodes
        assert "MATCH (n) DETACH DELETE n" not in query
        assert "repository_id" in query
        assert "tenant_id" in query

    def test_passes_correct_ids(self):
        client, session = make_client()
        repo_id = str(uuid4())
        tenant_id = str(uuid4())

        client.clear_repository(repository_id=repo_id, tenant_id=tenant_id)

        params = session.run.call_args[0][1]
        assert params["repository_id"] == repo_id
        assert params["tenant_id"] == tenant_id


# ---------------------------------------------------------------------------
# Integration smoke test (skipped unless INTEGRATION_NEO4J is set)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("INTEGRATION_NEO4J"),
    reason="Set INTEGRATION_NEO4J=1 to run against a live Neo4j instance"
)
class TestNeo4jIsolationIntegration:
    """
    End-to-end test: two tenants should never see each other's nodes.

    Requires a running Neo4j instance (docker-compose up neo4j).
    """

    def setup_method(self):
        from app.db.Neo4j_session import neo4j_client
        self.client = neo4j_client
        self.client.clear_all()

    def test_tenant_a_cannot_see_tenant_b_nodes(self):
        t_a = str(uuid4())
        t_b = str(uuid4())
        repo_a = str(uuid4())
        repo_b = str(uuid4())

        self.client.create_service_node("shared_name", tenant_id=t_a, repository_id=repo_a)
        self.client.create_service_node("shared_name", tenant_id=t_b, repository_id=repo_b)
        self.client.create_dependency_edge(
            "shared_name", "callee_a", "GET", "http://callee_a/api",
            tenant_id=t_a, repository_id=repo_a, confidence=0.9,
        )
        self.client.create_dependency_edge(
            "shared_name", "callee_b", "GET", "http://callee_b/api",
            tenant_id=t_b, repository_id=repo_b, confidence=0.9,
        )

        deps_a = self.client.get_service_dependencies("shared_name", tenant_id=t_a)
        deps_b = self.client.get_service_dependencies("shared_name", tenant_id=t_b)

        a_callees = {r["service"] for r in deps_a}
        b_callees = {r["service"] for r in deps_b}

        assert "callee_a" in a_callees
        assert "callee_b" not in a_callees
        assert "callee_b" in b_callees
        assert "callee_a" not in b_callees
