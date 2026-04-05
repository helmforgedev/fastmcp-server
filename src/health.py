"""Health check endpoints for FastMCP server.

Provides Kubernetes-compatible health probes:
  - GET /healthz  — Liveness (server is running)
  - GET /readyz   — Readiness (sources synced, components loaded)
  - GET /startupz — Startup (full initialization complete)
"""

import logging
import time

from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("fastmcp-server.health")

# Server state tracking
_state = {
    "started_at": None,
    "sources_synced": False,
    "components_loaded": False,
    "startup_complete": False,
    "component_counts": {"tools": 0, "resources": 0, "prompts": 0, "knowledge": 0},
}


def mark_sources_synced() -> None:
    _state["sources_synced"] = True


def mark_components_loaded(counts: dict) -> None:
    _state["components_loaded"] = True
    _state["component_counts"] = {
        "tools": counts.get("tool_count", 0),
        "resources": counts.get("resource_count", 0),
        "prompts": counts.get("prompt_count", 0),
        "knowledge": counts.get("knowledge_count", 0),
    }


def mark_startup_complete() -> None:
    _state["startup_complete"] = True
    _state["started_at"] = time.time()


def get_state() -> dict:
    return _state.copy()


async def healthz(request: Request) -> JSONResponse:
    """Liveness probe — server process is running."""
    return JSONResponse({"status": "ok"}, status_code=200)


async def readyz(request: Request) -> JSONResponse:
    """Readiness probe — sources synced and at least one component loaded."""
    if not _state["sources_synced"]:
        return JSONResponse(
            {"status": "not_ready", "reason": "sources not synced"}, status_code=503
        )

    total = sum(_state["component_counts"].values())
    if total == 0:
        return JSONResponse(
            {"status": "not_ready", "reason": "no components loaded"}, status_code=503
        )

    return JSONResponse(
        {"status": "ready", "components": _state["component_counts"]}, status_code=200
    )


async def startupz(request: Request) -> JSONResponse:
    """Startup probe — full server initialization complete."""
    if not _state["startup_complete"]:
        return JSONResponse(
            {"status": "starting", "reason": "initialization in progress"},
            status_code=503,
        )

    uptime = time.time() - _state["started_at"] if _state["started_at"] else 0
    return JSONResponse(
        {
            "status": "started",
            "uptime_seconds": round(uptime, 1),
            "components": _state["component_counts"],
        },
        status_code=200,
    )
