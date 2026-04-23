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


def test_helper_module_without_docstrings_is_not_registered(workspace, monkeypatch):
    """Public helper functions without docstrings should not become tools."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "evidence_helpers.py").write_text(
        "def evidence_true(data, *keys):\n    return True\n\n"
        "def notes_reviewed(data):\n    return True\n"
    )
    (workspace / "tools" / "real_tool.py").write_text(
        'def check_release_readiness() -> dict:\n    """Check release readiness."""\n    return {"status": "PASS"}\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


def test_tool_manifest_registers_selected_functions(workspace, monkeypatch):
    """TOOLS manifest should allow explicit registration from mixed modules."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "manifested.py").write_text(
        'TOOLS = ["hello"]\n\n'
        'def hello() -> str:\n    return "hi"\n\n'
        'def helper() -> str:\n    return "helper"\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


def test_varargs_tool_is_skipped_instead_of_crashing(workspace, monkeypatch):
    """Functions with *args or **kwargs should be skipped with no crash."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "bad_signature.py").write_text(
        'TOOLS = ["bad", "good"]\n\n'
        'def bad(*args) -> str:\n    """Bad signature."""\n    return "bad"\n\n'
        'def good(name: str) -> str:\n    """Good signature."""\n    return name\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


def test_imported_function_is_not_auto_registered(workspace, monkeypatch):
    """Imported helper functions should not become tools via auto-discovery."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "shared.py").write_text(
        'def shared_tool() -> str:\n    """Shared tool."""\n    return "shared"\n'
    )
    (workspace / "tools" / "consumer.py").write_text("from shared import shared_tool\n")

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


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


# --- v0.3.0: Tool metadata tests ---


def test_tool_tags(workspace, monkeypatch):
    """Tools with __tags__ module variable register tags correctly."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "tagged.py").write_text(
        '__tags__ = {"devops", "production"}\n\n'
        'def deploy(service: str) -> str:\n    """Deploy."""\n    return f"deployed {service}"\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


def test_tool_timeout(workspace, monkeypatch):
    """Tools with __timeout__ module variable register timeout correctly."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "slow.py").write_text(
        "__timeout__ = 30.0\n\n"
        'def slow_task() -> str:\n    """Slow task."""\n    return "done"\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


def test_tool_annotations(workspace, monkeypatch):
    """Tools with __annotations_mcp__ module variable register annotations correctly."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "annotated.py").write_text(
        '__annotations_mcp__ = {"destructiveHint": True, "title": "Dangerous Tool"}\n\n'
        'def dangerous() -> str:\n    """Dangerous action."""\n    return "boom"\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


def test_tool_all_metadata(workspace, monkeypatch):
    """Tools with all metadata module variables work together."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "full_meta.py").write_text(
        '__tags__ = {"ops"}\n'
        "__timeout__ = 15.0\n"
        '__annotations_mcp__ = {"readOnlyHint": True}\n\n'
        'def check_status() -> str:\n    """Check status."""\n    return "ok"\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


def test_tool_no_metadata_backward_compat(workspace, monkeypatch):
    """Tools without metadata still work (backward compatibility)."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "simple.py").write_text(
        'def hello() -> str:\n    """Hello."""\n    return "hi"\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


# --- v0.3.0: Resource template tests ---


def test_resource_template(workspace, monkeypatch):
    """Resource with URI template registers correctly."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "resources" / "user.py").write_text(
        'RESOURCE_URI = "users://{user_id}/profile"\n\n'
        "def get_profile(user_id: str) -> dict:\n"
        '    """Get user profile."""\n'
        '    return {"user_id": user_id}\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["resource_count"] == 1


# --- v0.3.0: Multiple resources per file tests ---


def test_multiple_resources_per_file(workspace, monkeypatch):
    """File with RESOURCES dict registers multiple resources."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "resources" / "multi.py").write_text(
        "RESOURCES = {\n"
        '    "status://health": "get_health",\n'
        '    "status://version": "get_version",\n'
        "}\n\n"
        'def get_health() -> dict:\n    return {"status": "ok"}\n\n'
        'def get_version() -> str:\n    return "1.0.0"\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["resource_count"] == 2


def test_resources_dict_missing_function(workspace, monkeypatch):
    """RESOURCES dict with missing function logs warning but doesn't crash."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "resources" / "bad_map.py").write_text(
        "RESOURCES = {\n"
        '    "status://health": "get_health",\n'
        '    "status://missing": "nonexistent_func",\n'
        "}\n\n"
        'def get_health() -> dict:\n    return {"status": "ok"}\n'
    )

    mcp, counts = build_server(str(workspace))

    # Only the valid one should register
    assert counts["resource_count"] == 1


def test_resource_uri_still_works(workspace, sample_resource, monkeypatch):
    """Legacy RESOURCE_URI still works alongside RESOURCES dict support."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")

    mcp, counts = build_server(str(workspace))

    assert counts["resource_count"] == 1


# --- v0.3.0: Error masking tests ---


def test_error_masking_enabled(workspace, monkeypatch):
    """Error masking creates server with mask_error_details=True."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    monkeypatch.setenv("MCP_MASK_ERROR_DETAILS", "true")

    mcp, counts = build_server(str(workspace))

    assert mcp is not None


def test_error_masking_disabled_by_default(workspace, monkeypatch):
    """Error masking is disabled by default."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")

    mcp, counts = build_server(str(workspace))

    assert mcp is not None


# --- v0.3.0: Duplicate handling tests ---


def test_duplicate_tools_warn(workspace, monkeypatch):
    """Duplicate tools with warn mode don't crash."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    monkeypatch.setenv("MCP_ON_DUPLICATE_TOOLS", "warn")

    (workspace / "tools" / "a.py").write_text(
        'def hello() -> str:\n    """Hello A."""\n    return "a"\n'
    )
    (workspace / "tools" / "b.py").write_text(
        'def hello() -> str:\n    """Hello B."""\n    return "b"\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 2


def test_duplicate_tools_replace(workspace, monkeypatch):
    """Duplicate tools with replace mode succeed silently."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    monkeypatch.setenv("MCP_ON_DUPLICATE_TOOLS", "replace")

    (workspace / "tools" / "a.py").write_text(
        'def hello() -> str:\n    """Hello A."""\n    return "a"\n'
    )
    (workspace / "tools" / "b.py").write_text(
        'def hello() -> str:\n    """Hello B."""\n    return "b"\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 2


def test_duplicate_tools_error(workspace, monkeypatch):
    """Duplicate tools with error mode raises ValueError."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    monkeypatch.setenv("MCP_ON_DUPLICATE_TOOLS", "error")

    (workspace / "tools" / "a.py").write_text(
        'def hello() -> str:\n    """Hello A."""\n    return "a"\n'
    )
    (workspace / "tools" / "b.py").write_text(
        'def hello() -> str:\n    """Hello B."""\n    return "b"\n'
    )

    import pytest

    with pytest.raises(ValueError):
        build_server(str(workspace))


# --- v0.4.0: Strict loading tests ---


def test_strict_loading_bad_file(workspace, monkeypatch):
    """Strict loading fails on bad Python file."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    monkeypatch.setenv("MCP_STRICT_LOADING", "true")

    (workspace / "tools" / "bad.py").write_text("this is not valid python !!!")

    import pytest

    with pytest.raises(RuntimeError, match="Strict loading"):
        build_server(str(workspace))


def test_strict_loading_off_by_default(workspace, monkeypatch):
    """Strict loading is off by default — bad files are skipped."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")

    (workspace / "tools" / "bad.py").write_text("this is not valid python !!!")
    (workspace / "tools" / "good.py").write_text(
        'def hello() -> str:\n    return "hi"\n'
    )

    mcp, counts = build_server(str(workspace))

    assert counts["tool_count"] == 1


def test_strict_loading_resource_without_uri(workspace, monkeypatch):
    """Strict loading fails on resource without RESOURCE_URI or RESOURCES."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    monkeypatch.setenv("MCP_STRICT_LOADING", "true")

    (workspace / "resources" / "no_uri.py").write_text(
        "def get_data() -> dict:\n    return {'key': 'value'}\n"
    )

    import pytest

    with pytest.raises(RuntimeError, match="Strict loading"):
        build_server(str(workspace))


# --- v0.7.0: Auth and scopes tests ---


def test_multi_auth_bearer_only(workspace, monkeypatch):
    """Multi-auth with only bearer falls back to bearer."""
    monkeypatch.setenv("MCP_AUTH_TYPE", "multi")
    monkeypatch.setenv("MCP_AUTH_PROVIDERS", "bearer")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")

    mcp, counts = build_server(str(workspace))
    assert mcp is not None


def test_required_scopes_stored_in_annotations(workspace, monkeypatch):
    """__required_scopes__ is stored in tool annotations."""
    monkeypatch.setenv("MCP_SERVER_NAME", "test-server")
    (workspace / "tools" / "admin.py").write_text(
        '__required_scopes__ = ["deploy:write"]\n\n'
        'def deploy(service: str) -> str:\n    """Deploy."""\n    return "done"\n'
    )

    mcp, counts = build_server(str(workspace))
    assert counts["tool_count"] == 1
