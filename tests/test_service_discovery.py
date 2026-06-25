"""
Unit tests for Service Discovery.
"""

import os
from app.extraction.service_discovery import discover_services


def test_discover_services_microservices_demo():
    repo_path = "benchmark/repos/microservices-demo"
    if os.path.exists(repo_path):
        services = discover_services(repo_path)
        # Expected services inside src/
        expected = {"ad", "cart", "checkout", "currency", "email", "frontend", "payment", "productcatalog", "recommendation", "shipping", "shoppingassistant"}
        # Check that the discovered set includes these normalized names
        assert expected.issubset(set(services))


def test_discover_services_go_coffeeshop():
    repo_path = "benchmark/repos/go-coffeeshop"
    if os.path.exists(repo_path):
        services = discover_services(repo_path)
        # Expected services inside cmd/
        expected = {"barista", "counter", "kitchen", "product", "proxy", "web"}
        assert expected.issubset(set(services))


def test_discover_services_robusta():
    repo_path = "benchmark/repos/robusta"
    if os.path.exists(repo_path):
        services = discover_services(repo_path)
        # Expected robusta under src/
        assert "robusta" in services


def test_discover_services_non_existent():
    services = discover_services("non_existent_directory_12345")
    assert services == []
