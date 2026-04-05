"""Tests for rebuild_components function."""

from server_builder import build_server, rebuild_components


def test_rebuild_updates_components(workspace, monkeypatch):
    """Rebuild registers new tools added after initial build."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")

    (workspace / "tools" / "greet.py").write_text(
        'def greet() -> str:\n    """Greet."""\n    return "hi"\n'
    )
    mcp, counts = build_server(str(workspace))
    assert counts["tool_count"] == 1

    # Add another tool
    (workspace / "tools" / "math.py").write_text(
        'def add(a: int, b: int) -> int:\n    """Add."""\n    return a + b\n'
    )
    new_counts = rebuild_components(mcp, str(workspace))
    assert new_counts["tool_count"] == 2


def test_rebuild_clears_old_components(workspace, monkeypatch):
    """Rebuild clears old components before reloading."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")

    (workspace / "tools" / "greet.py").write_text(
        'def greet() -> str:\n    return "hi"\n'
    )
    mcp, counts = build_server(str(workspace))
    assert counts["tool_count"] == 1

    # Remove the tool file
    (workspace / "tools" / "greet.py").unlink()
    new_counts = rebuild_components(mcp, str(workspace))
    assert new_counts["tool_count"] == 0
