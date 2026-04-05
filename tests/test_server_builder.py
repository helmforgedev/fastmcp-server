"""Tests for the FastMCP server builder."""

from server_builder import build_server


def test_build_with_tools(workspace, sample_tool, monkeypatch):
    """Tools are registered correctly."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


def test_build_with_multiple_tools(workspace, monkeypatch):
    """Multiple tools from one file are all registered."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "math.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n\n"
        "def multiply(a: int, b: int) -> int:\n    return a * b\n"
    )
    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 2


def test_build_with_resources(workspace, sample_resource, monkeypatch):
    """Resources are registered correctly."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    mcp, counts = build_server(str(workspace))

    assert counts["resource_count"] == 1


def test_build_with_prompts(workspace, sample_prompt, monkeypatch):
    """Prompts are registered correctly."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    mcp, counts = build_server(str(workspace))

    assert counts["prompt_count"] == 1


def test_build_with_knowledge(workspace, sample_knowledge, monkeypatch):
    """Knowledge files are registered as resources."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    mcp, counts = build_server(str(workspace))

    assert counts["knowledge_count"] == 1


def test_build_empty_workspace(workspace, monkeypatch):
    """Empty workspace builds successfully with zero components."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 0
    assert counts["resource_count"] == 0
    assert counts["prompt_count"] == 0
    assert counts["knowledge_count"] == 0


def test_build_bad_python_file(workspace, monkeypatch):
    """Bad Python file doesn't crash the build."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")

    (workspace / "tools" / "bad.py").write_text("this is not valid python !!!")
    (workspace / "tools" / "good.py").write_text(
        "def hello() -> str:\n    return 'hi'\n"
    )

    mcp, counts = build_server(str(workspace))

    # Good tool still loaded despite bad file
    assert counts["tool_count"] == 1


def test_build_missing_import(workspace, monkeypatch):
    """Tool with missing import doesn't crash the build."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")

    (workspace / "tools" / "missing_dep.py").write_text(
        "import nonexistent_package_xyz\n\ndef tool(): return 'hi'\n"
    )
    (workspace / "tools" / "good.py").write_text(
        "def hello() -> str:\n    return 'hi'\n"
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


def test_build_auth_bearer(workspace, monkeypatch):
    """Bearer auth is configured when env vars are set."""
    monkeypatch.setenv("MCP_AUTH_TYPE", "bearer")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token-123")

    mcp, counts = build_server(str(workspace))

    # Server should build without error
    assert mcp is not None


def test_build_auth_none(workspace, monkeypatch):
    """No auth when MCP_AUTH_TYPE is none."""
    monkeypatch.setenv("MCP_AUTH_TYPE", "none")

    mcp, counts = build_server(str(workspace))

    assert mcp is not None


def test_build_resource_without_uri(workspace, monkeypatch):
    """Resource file without RESOURCE_URI is skipped."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "resources" / "no_uri.py").write_text(
        "def get_data() -> dict:\n    return {'key': 'value'}\n"
    )

    mcp, counts = build_server(str(workspace))

    assert counts["resource_count"] == 0


def test_build_all_components(
    workspace,
    sample_tool,
    sample_resource,
    sample_prompt,
    sample_knowledge,
    monkeypatch,
):
    """All component types load together."""
    monkeypatch.setenv("MCP_SERVER_NAME", "full-server")

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] >= 1
    assert counts["resource_count"] >= 1
    assert counts["prompt_count"] >= 1
    assert counts["knowledge_count"] >= 1
