"""Tests for Prometheus metrics module."""

import pytest

from metrics import (
    init_metrics,
    instrument_tool,
    is_enabled,
    record_source_sync,
    set_component_counts,
)


@pytest.fixture(autouse=True)
def reset_metrics(monkeypatch):
    """Reset metrics state between tests."""
    import metrics
    from prometheus_client import REGISTRY

    # Unregister any previously created collectors
    collectors_to_remove = []
    for collector in list(REGISTRY._names_to_collectors.values()):
        if hasattr(collector, "_name") and collector._name.startswith("mcp_"):
            collectors_to_remove.append(collector)
    for collector in set(collectors_to_remove):
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass

    metrics._ENABLED = False
    metrics._TOOLS_TOTAL = None
    metrics._RESOURCES_TOTAL = None
    metrics._PROMPTS_TOTAL = None
    metrics._KNOWLEDGE_TOTAL = None
    metrics._TOOL_CALLS = None
    metrics._TOOL_DURATION = None
    metrics._TOOL_ERRORS = None
    metrics._SOURCE_SYNC = None
    metrics._AUTH_REQUESTS = None
    yield


def test_metrics_disabled_by_default():
    """Metrics are disabled when env var not set."""
    init_metrics()
    assert not is_enabled()


def test_metrics_enabled(monkeypatch):
    """Metrics initialize when MCP_METRICS_ENABLED=true."""
    monkeypatch.setenv("MCP_METRICS_ENABLED", "true")
    init_metrics()
    assert is_enabled()


def test_set_component_counts_disabled():
    """set_component_counts is a no-op when disabled."""
    # Should not raise
    set_component_counts(tools=5, resources=3, prompts=1, knowledge=2)


def test_set_component_counts_enabled(monkeypatch):
    """set_component_counts sets gauge values when enabled."""
    monkeypatch.setenv("MCP_METRICS_ENABLED", "true")
    init_metrics()

    set_component_counts(tools=5, resources=3, prompts=1, knowledge=2)

    import metrics

    assert metrics._TOOLS_TOTAL._value.get() == 5
    assert metrics._RESOURCES_TOTAL._value.get() == 3


def test_record_source_sync_disabled():
    """record_source_sync is a no-op when disabled."""
    record_source_sync("s3", True)


def test_instrument_tool_disabled():
    """instrument_tool returns original function when disabled."""

    def my_tool(x: str) -> str:
        return f"hello {x}"

    result = instrument_tool(my_tool, "my_tool")
    assert result is my_tool


def test_instrument_tool_enabled(monkeypatch):
    """instrument_tool wraps function when enabled."""
    monkeypatch.setenv("MCP_METRICS_ENABLED", "true")
    init_metrics()

    def my_tool(x: str) -> str:
        return f"hello {x}"

    wrapped = instrument_tool(my_tool, "my_tool")
    assert wrapped is not my_tool

    # Call the wrapped function
    result = wrapped("world")
    assert result == "hello world"


def test_instrument_async_tool(monkeypatch):
    """instrument_tool wraps async functions correctly."""
    monkeypatch.setenv("MCP_METRICS_ENABLED", "true")
    init_metrics()

    async def async_tool(x: str) -> str:
        return f"async {x}"

    wrapped = instrument_tool(async_tool, "async_tool")
    assert wrapped is not async_tool

    import asyncio

    result = asyncio.run(wrapped("test"))
    assert result == "async test"
