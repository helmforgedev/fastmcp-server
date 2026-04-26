"""API endpoints for diagnostics and Web UI.

Provides JSON APIs consumed by the embedded UI:
  - GET /debug/info      — Server diagnostics
  - GET /api/info        — Server overview for UI
  - GET /api/tools       — List tools with schemas
  - GET /api/resources   — List resources
  - GET /api/prompts     — List prompts
"""

import logging
import os
import time

from starlette.requests import Request
from starlette.responses import JSONResponse

from authz import (
    authorize_http_request,
    env_flag,
    is_production_env,
    redact_secrets,
    safe_config_summary,
)

logger = logging.getLogger("fastmcp-server.api")

# Reference to FastMCP instance (set by entrypoint)
_mcp = None
_started_at = None
_source_info = {}

_UNAUTHORIZED = JSONResponse({"error": "unauthorized"}, status_code=401)


async def _check_auth(request: Request) -> bool:
    """Check authentication for API requests.

    Returns True when the request is authorized (or auth is disabled).
    """
    allowed, _, _ = await authorize_http_request(request)
    return allowed


def init_api(mcp, source_info: dict | None = None) -> None:
    """Initialize API with FastMCP instance reference."""
    global _mcp, _started_at, _source_info
    _mcp = mcp
    _started_at = time.time()
    _source_info = source_info or {}


def _get_version() -> str:
    return os.environ.get("MCP_SERVER_VERSION", "0.4.0")


def _get_fastmcp_version() -> str:
    try:
        import fastmcp

        return getattr(fastmcp, "__version__", "unknown")
    except Exception:
        return "unknown"


async def debug_info(request: Request) -> JSONResponse:
    """Diagnostic endpoint with full server information."""
    if not await _check_auth(request):
        return _UNAUTHORIZED
    if _mcp is None:
        return JSONResponse({"error": "server not initialized"}, status_code=503)

    server_name = os.environ.get("MCP_SERVER_NAME", "fastmcp-server")
    uptime = time.time() - _started_at if _started_at else 0
    extra_packages = os.environ.get("EXTRA_PIP_PACKAGES", "")

    # Extract component info from FastMCP
    tools = _extract_tools()
    resources = _extract_resources()
    prompts = _extract_prompts()

    return JSONResponse(
        redact_secrets(
            {
                "server": server_name,
                "version": _get_version(),
                "fastmcp_version": _get_fastmcp_version(),
                "uptime_seconds": round(uptime, 1),
                "components": {
                    "tools": tools,
                    "resources": resources,
                    "prompts": prompts,
                },
                "sources": _source_info,
                "auth": safe_config_summary(),
                "extra_packages": [
                    p.strip() for p in extra_packages.split(",") if p.strip()
                ],
                "cache": _get_cache_stats(),
                "config": {
                    "mask_error_details": env_flag(
                        "MCP_MASK_ERROR_DETAILS", default=is_production_env()
                    ),
                    "on_duplicate": os.environ.get("MCP_ON_DUPLICATE_TOOLS", "warn"),
                    "metrics_enabled": os.environ.get(
                        "MCP_METRICS_ENABLED", "false"
                    ).lower()
                    == "true",
                    "ui_enabled": os.environ.get("MCP_UI_ENABLED", "true").lower()
                    == "true",
                    "log_format": os.environ.get("LOG_FORMAT", "text"),
                    "rate_limit_default": os.environ.get("MCP_RATE_LIMIT_DEFAULT", ""),
                    "cache_enabled": os.environ.get("MCP_CACHE_ENABLED", "true").lower()
                    != "false",
                },
            }
        )
    )


async def api_info(request: Request) -> JSONResponse:
    """Server overview for UI dashboard."""
    if not await _check_auth(request):
        return _UNAUTHORIZED
    if _mcp is None:
        return JSONResponse({"error": "server not initialized"}, status_code=503)

    server_name = os.environ.get("MCP_SERVER_NAME", "fastmcp-server")
    uptime = time.time() - _started_at if _started_at else 0
    auth_type = os.environ.get("MCP_AUTH_TYPE", "none")

    tools = _extract_tools()
    resources = _extract_resources()
    prompts = _extract_prompts()

    return JSONResponse(
        redact_secrets(
            {
                "server": server_name,
                "version": _get_version(),
                "fastmcp_version": _get_fastmcp_version(),
                "uptime_seconds": round(uptime, 1),
                "auth_type": auth_type,
                "counts": {
                    "tools": len(tools),
                    "resources": len(resources),
                    "prompts": len(prompts),
                },
                "sources": _source_info,
            }
        )
    )


async def api_tools(request: Request) -> JSONResponse:
    """List all registered tools with schemas."""
    if not await _check_auth(request):
        return _UNAUTHORIZED
    return JSONResponse(_extract_tools())


async def api_resources(request: Request) -> JSONResponse:
    """List all registered resources."""
    if not await _check_auth(request):
        return _UNAUTHORIZED
    return JSONResponse(_extract_resources())


async def api_prompts(request: Request) -> JSONResponse:
    """List all registered prompts."""
    if not await _check_auth(request):
        return _UNAUTHORIZED
    return JSONResponse(_extract_prompts())


def _get_cache_stats() -> dict:
    """Get cache statistics for diagnostics."""
    try:
        from caching import get_cache_stats

        return get_cache_stats()
    except Exception:
        return {}


def _get_components() -> dict:
    """Get components dict from FastMCP's local provider."""
    if _mcp is None:
        return {}
    try:
        return _mcp._local_provider._components
    except AttributeError:
        return {}


def _extract_tools() -> list[dict]:
    """Extract tool information from FastMCP instance."""
    tools = []
    try:
        for key, component in _get_components().items():
            if not key.startswith("tool:"):
                continue
            info = {
                "name": getattr(component, "name", key),
                "description": getattr(component, "description", "") or "",
            }
            tags = getattr(component, "tags", None)
            if tags:
                info["tags"] = list(tags)
            timeout = getattr(component, "timeout", None)
            if timeout:
                info["timeout"] = timeout
            annotations = getattr(component, "annotations", None)
            if annotations:
                info["annotations"] = (
                    annotations if isinstance(annotations, dict) else str(annotations)
                )
            # Extract parameters from the function signature
            fn = getattr(component, "fn", None)
            if fn and hasattr(fn, "__annotations__"):
                params = {}
                for pname, ptype in fn.__annotations__.items():
                    if pname == "return":
                        continue
                    params[pname] = str(ptype)
                if params:
                    info["parameters"] = params
            tools.append(info)
    except Exception:
        logger.debug("Failed to extract tools", exc_info=True)
    return tools


def _extract_resources() -> list[dict]:
    """Extract resource information from FastMCP instance."""
    resources = []
    try:
        for key, component in _get_components().items():
            if not key.startswith("resource:") and not key.startswith("template:"):
                continue
            info = {
                "uri": str(getattr(component, "uri", key)),
                "name": getattr(component, "name", str(key)),
                "description": getattr(component, "description", "") or "",
                "mime_type": getattr(component, "mime_type", "text/plain"),
            }
            if key.startswith("template:"):
                info["is_template"] = True
            resources.append(info)
    except Exception:
        logger.debug("Failed to extract resources", exc_info=True)
    return resources


def _extract_prompts() -> list[dict]:
    """Extract prompt information from FastMCP instance."""
    prompts = []
    try:
        for key, component in _get_components().items():
            if not key.startswith("prompt:"):
                continue
            info = {
                "name": getattr(component, "name", key),
                "description": getattr(component, "description", "") or "",
            }
            prompts.append(info)
    except Exception:
        logger.debug("Failed to extract prompts", exc_info=True)
    return prompts
