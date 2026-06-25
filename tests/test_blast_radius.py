"""
Unit tests for Graph Builder and Blast Radius calculator.
"""

import pytest
import math
import networkx as nx

from app.analysis.graph_builder import build_graph
from app.analysis.blast_radius import compute_blast_radius, normalise


def test_normalise():
    assert normalise("payment_service") == "payment"
    assert normalise("checkout-client") == "checkout"
    assert normalise("api-gateway") == "apigateway"
    assert normalise("email-svc") == "email"
    assert normalise("OrderHandler") == "order"
    assert normalise("auth-server") == "auth"


def test_build_graph_merges_max_confidence():
    deps = [
        {"caller": "service-a", "callee": "service-b", "confidence": 0.5, "method": "GET", "url": "/a"},
        {"caller": "service_a", "callee": "service_b", "confidence": 0.8, "method": "POST", "url": "/b"},
        {"caller": "service-a", "callee": "service-b", "confidence": 0.3, "method": "PUT", "url": "/c"}
    ]
    graph = build_graph(deps)
    
    # Nodes should be normalized
    assert "servicea" in graph
    assert "serviceb" in graph
    
    # Edge confidence should be max (0.8)
    edge_data = graph["servicea"]["serviceb"]
    assert edge_data["confidence"] == 0.8
    assert edge_data["method"] == "POST"
    assert edge_data["url"] == "/b"
    assert abs(edge_data["weight"] - (-math.log(0.8))) < 1e-6


def test_compute_blast_radius_traversal():
    # Construct a simple line: a -> b -> c
    # Edge a -> b confidence = 0.9
    # Edge b -> c confidence = 0.8
    # Source = a:
    #   - b is outbound, confidence = 0.9, hops = 1, path = [a, b]
    #   - c is outbound, confidence = 0.9 * 0.8 = 0.72, hops = 2, path = [a, b, c]
    deps = [
        {"caller": "a", "callee": "b", "confidence": 0.9},
        {"caller": "b", "callee": "c", "confidence": 0.8}
    ]
    graph = build_graph(deps)
    
    # Compute starting from "a"
    res_a = compute_blast_radius(graph, "a", confidence_threshold=0.5)
    assert res_a["service"] == "a"
    
    affected = {item["service"]: item for item in res_a["affected_services"]}
    assert "b" in affected
    assert affected["b"]["confidence"] == 0.9
    assert affected["b"]["hops"] == 1
    assert affected["b"]["direction"] == "outbound"
    assert affected["b"]["path"] == ["a", "b"]
    
    assert "c" in affected
    assert abs(affected["c"]["confidence"] - 0.72) < 1e-4
    assert affected["c"]["hops"] == 2
    assert affected["c"]["direction"] == "outbound"
    assert affected["c"]["path"] == ["a", "b", "c"]

    # Compute starting from "c" (should find inbound)
    res_c = compute_blast_radius(graph, "c", confidence_threshold=0.5)
    assert res_c["service"] == "c"
    
    affected_c = {item["service"]: item for item in res_c["affected_services"]}
    assert "b" in affected_c
    assert affected_c["b"]["confidence"] == 0.8
    assert affected_c["b"]["hops"] == 1
    assert affected_c["b"]["direction"] == "inbound"
    assert affected_c["b"]["path"] == ["b", "c"]
    
    assert "a" in affected_c
    assert abs(affected_c["a"]["confidence"] - 0.72) < 1e-4
    assert affected_c["a"]["hops"] == 2
    assert affected_c["a"]["direction"] == "inbound"
    assert affected_c["a"]["path"] == ["a", "b", "c"]


def test_compute_blast_radius_bidirectional_deduplicate():
    # Mutual calls: a -> b (0.9), b -> a (0.7)
    # Plus: a -> c (0.8), c -> a (0.9)
    deps = [
        {"caller": "a", "callee": "b", "confidence": 0.9},
        {"caller": "b", "callee": "a", "confidence": 0.7},
        {"caller": "a", "callee": "c", "confidence": 0.8},
        {"caller": "c", "callee": "a", "confidence": 0.9}
    ]
    graph = build_graph(deps)
    
    res = compute_blast_radius(graph, "a", confidence_threshold=0.5)
    affected = {item["service"]: item for item in res["affected_services"]}
    
    # "b" is reachable outbound (a -> b) at 0.9
    # "b" is reachable inbound (b -> a) at 0.7
    # Deduplication keeps 0.9 and direction "both"
    assert "b" in affected
    assert affected["b"]["confidence"] == 0.9
    assert affected["b"]["direction"] == "both"
    
    # "c" is reachable outbound (a -> c) at 0.8
    # "c" is reachable inbound (c -> a) at 0.9
    # Deduplication keeps 0.9 (the inbound path c -> a) and direction "both"
    assert "c" in affected
    assert affected["c"]["confidence"] == 0.9
    assert affected["c"]["direction"] == "both"


def test_compute_blast_radius_threshold():
    # a -> b (0.8) -> c (0.5)
    deps = [
        {"caller": "a", "callee": "b", "confidence": 0.8},
        {"caller": "b", "callee": "c", "confidence": 0.5}
    ]
    graph = build_graph(deps)
    
    # Threshold = 0.5:
    # a -> b (0.8) is kept.
    # a -> c (0.8 * 0.5 = 0.4) is below threshold and should be filtered out.
    res = compute_blast_radius(graph, "a", confidence_threshold=0.5)
    affected = {item["service"]: item for item in res["affected_services"]}
    assert "b" in affected
    assert "c" not in affected


def test_compute_blast_radius_cycle():
    # Cycle: a -> b (0.9) -> c (0.9) -> a (0.9)
    deps = [
        {"caller": "a", "callee": "b", "confidence": 0.9},
        {"caller": "b", "callee": "c", "confidence": 0.9},
        {"caller": "c", "callee": "a", "confidence": 0.9}
    ]
    graph = build_graph(deps)
    
    res = compute_blast_radius(graph, "a", confidence_threshold=0.1)
    affected = {item["service"]: item for item in res["affected_services"]}
    
    # We should have traversed and found b and c, but not stuck in infinite loop
    assert "b" in affected
    assert "c" in affected


def test_compute_blast_radius_unknown_service():
    deps = [
        {"caller": "a", "callee": "b", "confidence": 0.9}
    ]
    graph = build_graph(deps)
    with pytest.raises(ValueError) as exc:
        compute_blast_radius(graph, "unknown", confidence_threshold=0.5)
    assert "not found in dependency graph" in str(exc.value)
    assert "Available services" in str(exc.value)
