"""Webhook endpoint for triggering source re-sync.

POST /reload — forces re-sync of all sources and component reload.
Protected by the same auth as the MCP server.
"""

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from authz import authorize_http_request, env_flag, redact_secrets

logger = logging.getLogger("fastmcp-server.reload")

_sync_fn = None
_rebuild_fn = None
_mcp = None
_workspace = None


def init_reload(mcp, workspace: str, sync_fn, rebuild_fn) -> None:
    """Initialize reload endpoint with sync and rebuild functions."""
    global _mcp, _workspace, _sync_fn, _rebuild_fn
    _mcp = mcp
    _workspace = workspace
    _sync_fn = sync_fn
    _rebuild_fn = rebuild_fn


async def reload_endpoint(request: Request) -> JSONResponse:
    """Force re-sync of all sources and reload components."""
    allowed, _, _ = await authorize_http_request(request)
    if not allowed:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if _sync_fn is None or _rebuild_fn is None:
        return JSONResponse({"error": "reload not initialized"}, status_code=503)

    try:
        from metrics import record_source_sync

        _sync_fn(_workspace)
        record_source_sync("webhook", True)

        _rebuild_fn(_mcp, _workspace)

        logger.info("Manual reload triggered successfully")
        return JSONResponse({"status": "reloaded"}, status_code=200)
    except Exception as e:
        logger.exception("Manual reload failed")
        from metrics import record_source_sync

        record_source_sync("webhook", False)
        detail = (
            "reload failed"
            if env_flag("MCP_MASK_ERROR_DETAILS")
            else redact_secrets(str(e))
        )
        return JSONResponse({"status": "error", "detail": detail}, status_code=500)
