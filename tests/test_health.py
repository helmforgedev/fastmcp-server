"""Tests for health check endpoints."""

import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route

from health import (
    healthz,
    mark_components_loaded,
    mark_sources_synced,
    mark_startup_complete,
    readyz,
    startupz,
    _state,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset health state between tests."""
    _state["started_at"] = None
    _state["sources_synced"] = False
    _state["components_loaded"] = False
    _state["startup_complete"] = False
    _state["component_counts"] = {
        "tools": 0,
        "resources": 0,
        "prompts": 0,
        "knowledge": 0,
    }
    yield


@pytest.fixture
def client():
    app = Starlette(
        routes=[
            Route("/healthz", healthz),
            Route("/readyz", readyz),
            Route("/startupz", startupz),
        ]
    )
    return TestClient(app)


def test_healthz_always_ok(client):
    """Liveness probe always returns 200."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_not_ready_before_sync(client):
    """Readiness returns 503 before sources are synced."""
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert "not synced" in resp.json()["reason"]


def test_readyz_not_ready_no_components(client):
    """Readiness returns 503 when synced but no components loaded."""
    mark_sources_synced()
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert "no components" in resp.json()["reason"]


def test_readyz_ready(client):
    """Readiness returns 200 when sources synced and components loaded."""
    mark_sources_synced()
    mark_components_loaded(
        {"tool_count": 3, "resource_count": 1, "prompt_count": 0, "knowledge_count": 0}
    )
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_startupz_not_ready(client):
    """Startup probe returns 503 before startup complete."""
    resp = client.get("/startupz")
    assert resp.status_code == 503
    assert "initialization" in resp.json()["reason"]


def test_startupz_ready(client):
    """Startup probe returns 200 after startup complete."""
    mark_sources_synced()
    mark_components_loaded(
        {"tool_count": 1, "resource_count": 0, "prompt_count": 0, "knowledge_count": 0}
    )
    mark_startup_complete()
    resp = client.get("/startupz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert "uptime_seconds" in resp.json()
