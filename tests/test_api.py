"""Tests for API and diagnostic endpoints."""

import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route

from api import api_info, api_prompts, api_resources, api_tools, debug_info, init_api
from server_builder import build_server


@pytest.fixture
def server(workspace, sample_tool, sample_resource, sample_prompt, monkeypatch):
    """Build a server with all component types."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    mcp, counts = build_server(str(workspace))
    init_api(mcp, {"inline": {"status": "loaded", "files": 3}})
    return mcp


@pytest.fixture
def client(server):
    app = Starlette(
        routes=[
            Route("/debug/info", debug_info),
            Route("/api/info", api_info),
            Route("/api/tools", api_tools),
            Route("/api/resources", api_resources),
            Route("/api/prompts", api_prompts),
        ]
    )
    return TestClient(app)


def test_debug_info(client, monkeypatch):
    """Debug info returns complete server diagnostics."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    resp = client.get("/debug/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["server"] == "test-server"
    assert "version" in data
    assert "components" in data
    assert "sources" in data
    assert "config" in data


def test_api_info(client, monkeypatch):
    """API info returns overview for UI."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    resp = client.get("/api/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["server"] == "test-server"
    assert "counts" in data
    assert "uptime_seconds" in data


def test_api_tools(client):
    """API tools returns tool list."""
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert isinstance(tools, list)
    assert len(tools) >= 1
    assert "name" in tools[0]


def test_api_resources(client):
    """API resources returns resource list."""
    resp = client.get("/api/resources")
    assert resp.status_code == 200
    resources = resp.json()
    assert isinstance(resources, list)
    assert len(resources) >= 1


def test_api_prompts(client):
    """API prompts returns prompt list."""
    resp = client.get("/api/prompts")
    assert resp.status_code == 200
    prompts = resp.json()
    assert isinstance(prompts, list)
    assert len(prompts) >= 1


def test_debug_info_before_init():
    """Debug info returns 503 before server is initialized."""
    import api

    old_mcp = api._mcp
    api._mcp = None

    app = Starlette(routes=[Route("/debug/info", debug_info)])
    client = TestClient(app)
    resp = client.get("/debug/info")
    assert resp.status_code == 503

    api._mcp = old_mcp
