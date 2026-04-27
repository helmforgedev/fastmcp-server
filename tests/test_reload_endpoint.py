"""Tests for reload webhook endpoint."""

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from reload_endpoint import init_reload, reload_endpoint
from server_builder import build_server, rebuild_components


@pytest.fixture
def workspace_with_tool(workspace):
    """Workspace with a tool file."""
    (workspace / "tools" / "greet.py").write_text(
        'def greet(name: str) -> str:\n    """Greet."""\n    return f"Hello, {name}!"\n'
    )
    return workspace


@pytest.fixture
def server(workspace_with_tool, monkeypatch):
    """Build a server for reload testing."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    mcp, counts = build_server(str(workspace_with_tool))
    return mcp, workspace_with_tool


@pytest.fixture
def client(server, monkeypatch):
    mcp, ws = server

    def fake_sync(workspace):
        pass

    init_reload(mcp, str(ws), fake_sync, rebuild_components)
    app = Starlette(routes=[Route("/reload", reload_endpoint, methods=["POST"])])
    return TestClient(app)


def test_reload_success(client):
    """POST /reload succeeds."""
    resp = client.post("/reload")
    assert resp.status_code == 200
    assert resp.json()["status"] == "reloaded"


def test_reload_before_init():
    """POST /reload returns 503 before init."""
    import reload_endpoint

    old = (reload_endpoint._sync_fn, reload_endpoint._rebuild_fn)
    reload_endpoint._sync_fn = None
    reload_endpoint._rebuild_fn = None

    app = Starlette(
        routes=[Route("/reload", reload_endpoint.reload_endpoint, methods=["POST"])]
    )
    client = TestClient(app)
    resp = client.post("/reload")
    assert resp.status_code == 503

    reload_endpoint._sync_fn, reload_endpoint._rebuild_fn = old
