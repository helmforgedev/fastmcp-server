"""Tests for gateway configuration parsing."""

from gateway import get_mount_config, is_gateway_mode


def test_gateway_mode_default(monkeypatch):
    """Default mode is server, not gateway."""
    assert not is_gateway_mode()


def test_gateway_mode_enabled(monkeypatch):
    """Gateway mode enabled via env var."""
    monkeypatch.setenv("MCP_MODE", "gateway")
    assert is_gateway_mode()


def test_mount_config_empty():
    """Empty MCP_MOUNT_SERVERS returns empty list."""
    servers = get_mount_config()
    assert servers == []


def test_mount_config_valid(monkeypatch):
    """Valid JSON array parses correctly."""
    monkeypatch.setenv(
        "MCP_MOUNT_SERVERS",
        '[{"name": "weather", "url": "http://weather:8000/mcp", "namespace": "wx"}]',
    )
    servers = get_mount_config()
    assert len(servers) == 1
    assert servers[0]["name"] == "weather"
    assert servers[0]["namespace"] == "wx"


def test_mount_config_invalid_json(monkeypatch):
    """Invalid JSON returns empty list."""
    monkeypatch.setenv("MCP_MOUNT_SERVERS", "not json")
    servers = get_mount_config()
    assert servers == []


def test_mount_config_not_array(monkeypatch):
    """Non-array JSON returns empty list."""
    monkeypatch.setenv("MCP_MOUNT_SERVERS", '{"name": "test"}')
    servers = get_mount_config()
    assert servers == []
