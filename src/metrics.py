"""Prometheus metrics for FastMCP server.

Exposes tool call counts, durations, errors, source sync status,
and auth request counts via /metrics endpoint.

Activated via MCP_METRICS_ENABLED=true environment variable.
"""

import functools
import logging
import os
import time
import types

logger = logging.getLogger("fastmcp-server.metrics")

_ENABLED = False
_TOOLS_TOTAL = None
_RESOURCES_TOTAL = None
_PROMPTS_TOTAL = None
_KNOWLEDGE_TOTAL = None
_TOOL_CALLS = None
_TOOL_DURATION = None
_TOOL_ERRORS = None
_SOURCE_SYNC = None
_AUTH_REQUESTS = None


def is_enabled() -> bool:
    return _ENABLED


def init_metrics() -> None:
    """Initialize Prometheus metrics if enabled."""
    global _ENABLED
    global _TOOLS_TOTAL, _RESOURCES_TOTAL, _PROMPTS_TOTAL, _KNOWLEDGE_TOTAL
    global _TOOL_CALLS, _TOOL_DURATION, _TOOL_ERRORS
    global _SOURCE_SYNC, _AUTH_REQUESTS

    if os.environ.get("MCP_METRICS_ENABLED", "false").lower() != "true":
        return

    from prometheus_client import Counter, Gauge, Histogram

    _ENABLED = True

    _TOOLS_TOTAL = Gauge("mcp_tools_total", "Number of registered tools")
    _RESOURCES_TOTAL = Gauge("mcp_resources_total", "Number of registered resources")
    _PROMPTS_TOTAL = Gauge("mcp_prompts_total", "Number of registered prompts")
    _KNOWLEDGE_TOTAL = Gauge(
        "mcp_knowledge_total", "Number of registered knowledge files"
    )

    _TOOL_CALLS = Counter("mcp_tool_calls_total", "Total tool invocations", ["tool"])
    _TOOL_DURATION = Histogram(
        "mcp_tool_duration_seconds",
        "Tool execution duration in seconds",
        ["tool"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )
    _TOOL_ERRORS = Counter(
        "mcp_tool_errors_total", "Total tool invocation errors", ["tool"]
    )
    _SOURCE_SYNC = Counter(
        "mcp_sources_sync_total", "Source sync operations", ["source", "status"]
    )
    _AUTH_REQUESTS = Counter(
        "mcp_auth_requests_total", "Authentication attempts", ["result"]
    )

    logger.info("Prometheus metrics enabled")


def set_component_counts(
    tools: int, resources: int, prompts: int, knowledge: int
) -> None:
    """Set gauge values for registered components."""
    if not _ENABLED:
        return
    _TOOLS_TOTAL.set(tools)
    _RESOURCES_TOTAL.set(resources)
    _PROMPTS_TOTAL.set(prompts)
    _KNOWLEDGE_TOTAL.set(knowledge)


def record_source_sync(source: str, success: bool) -> None:
    """Record a source sync operation."""
    if not _ENABLED:
        return
    _SOURCE_SYNC.labels(source=source, status="success" if success else "error").inc()


def record_auth(result: str) -> None:
    """Record an auth attempt (success/rejected)."""
    if not _ENABLED:
        return
    _AUTH_REQUESTS.labels(result=result).inc()


def instrument_tool(func: types.FunctionType, tool_name: str):
    """Wrap a tool function with metrics instrumentation."""
    if not _ENABLED:
        return func

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            _TOOL_CALLS.labels(tool=tool_name).inc()
            return result
        except Exception:
            _TOOL_ERRORS.labels(tool=tool_name).inc()
            _TOOL_CALLS.labels(tool=tool_name).inc()
            raise
        finally:
            duration = time.perf_counter() - start
            _TOOL_DURATION.labels(tool=tool_name).observe(duration)

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            _TOOL_CALLS.labels(tool=tool_name).inc()
            return result
        except Exception:
            _TOOL_ERRORS.labels(tool=tool_name).inc()
            _TOOL_CALLS.labels(tool=tool_name).inc()
            raise
        finally:
            duration = time.perf_counter() - start
            _TOOL_DURATION.labels(tool=tool_name).observe(duration)

    import inspect

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def get_metrics_app():
    """Return a Starlette app that serves /metrics."""
    from prometheus_client import generate_latest
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Route

    async def metrics_endpoint(request):
        return Response(
            content=generate_latest(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return Starlette(routes=[Route("/metrics", metrics_endpoint)])
