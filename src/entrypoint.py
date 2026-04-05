"""FastMCP Server Entrypoint.

Loads tools, resources, and prompts from multiple sources (inline, S3, Git),
builds a FastMCP server, and starts it via Uvicorn.
"""

import logging
import os
import signal
import subprocess
import sys

import uvicorn
from starlette.routing import Mount, Route

from api import api_info, api_prompts, api_resources, api_tools, debug_info, init_api
from health import (
    healthz,
    mark_components_loaded,
    mark_sources_synced,
    mark_startup_complete,
    readyz,
    startupz,
)
from loader import sync_sources
from logging_config import configure_logging
from metrics import init_metrics, is_enabled as metrics_enabled, set_component_counts
from server_builder import build_server

# Configure logging first
configure_logging()
logger = logging.getLogger("fastmcp-server")


def _install_extra_packages() -> None:
    """Install extra pip packages specified via EXTRA_PIP_PACKAGES env var."""
    packages = os.environ.get("EXTRA_PIP_PACKAGES", "").strip()
    if not packages:
        return

    pkg_list = [p.strip() for p in packages.split(",") if p.strip()]
    if not pkg_list:
        return

    logger.info("Installing extra packages: %s", ", ".join(pkg_list))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--quiet",
            *pkg_list,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Failed to install extra packages: %s", result.stderr.strip())
    else:
        logger.info("Extra packages installed successfully")


def _print_banner(
    server_name: str,
    tool_count: int,
    resource_count: int,
    prompt_count: int,
    knowledge_count: int,
) -> None:
    """Print startup banner with server info."""
    sources = []
    if os.path.isdir(os.environ.get("SOURCE_INLINE_DIR", "/app/inline")):
        sources.append("inline")
    if os.environ.get("SOURCE_S3_ENABLED", "false").lower() == "true":
        sources.append("s3")
    if os.environ.get("SOURCE_GIT_ENABLED", "false").lower() == "true":
        sources.append("git")

    auth_type = os.environ.get("MCP_AUTH_TYPE", "none")

    logger.info("=" * 50)
    logger.info("  fastmcp-server")
    logger.info("  Server: %s", server_name)
    logger.info("  Sources: %s", ", ".join(sources) if sources else "none")
    logger.info("  Auth: %s", auth_type)
    logger.info(
        "  Tools: %d | Resources: %d | Prompts: %d | Knowledge: %d",
        tool_count,
        resource_count,
        prompt_count,
        knowledge_count,
    )
    logger.info("=" * 50)


def _build_source_info() -> dict:
    """Collect source status information for API/diagnostics."""
    info = {}
    inline_dir = os.environ.get("SOURCE_INLINE_DIR", "/app/inline")
    if os.path.isdir(inline_dir):
        from pathlib import Path

        files = sum(1 for _ in Path(inline_dir).rglob("*") if _.is_file())
        info["inline"] = {"status": "loaded", "files": files}

    if os.environ.get("SOURCE_S3_ENABLED", "false").lower() == "true":
        info["s3"] = {
            "status": "synced",
            "bucket": os.environ.get("SOURCE_S3_BUCKET", ""),
        }

    if os.environ.get("SOURCE_GIT_ENABLED", "false").lower() == "true":
        info["git"] = {
            "status": "cloned",
            "repository": os.environ.get("SOURCE_GIT_REPOSITORY", ""),
            "branch": os.environ.get("SOURCE_GIT_BRANCH", "main"),
        }

    return info


def main() -> None:
    server_name = os.environ.get("MCP_SERVER_NAME", "fastmcp-server")
    workspace = os.environ.get("MCP_WORKSPACE", "/app/workspace")

    # Step 1: Initialize metrics if enabled
    init_metrics()

    # Step 2: Install extra pip packages if requested
    _install_extra_packages()

    # Step 3: Sync external sources (S3, Git, Inline) into workspace
    try:
        sync_sources(workspace)
        mark_sources_synced()
    except Exception:
        logger.exception("Failed to sync sources")
        sys.exit(1)

    # Step 4: Build FastMCP server from loaded files
    mcp, counts = build_server(workspace)
    mark_components_loaded(counts)

    # Step 5: Print startup banner
    _print_banner(server_name, **counts)

    # Step 6: Set metrics gauges
    if metrics_enabled():
        set_component_counts(
            tools=counts["tool_count"],
            resources=counts["resource_count"],
            prompts=counts["prompt_count"],
            knowledge=counts["knowledge_count"],
        )

    # Step 7: Initialize API with server reference
    source_info = _build_source_info()
    init_api(mcp, source_info)

    # Step 8: Create HTTP app with additional routes
    path = os.environ.get("MCP_PATH", "/mcp")
    app = mcp.http_app(path=path)

    # Add health endpoints
    app.routes.insert(0, Route("/healthz", healthz))
    app.routes.insert(0, Route("/readyz", readyz))
    app.routes.insert(0, Route("/startupz", startupz))

    # Add diagnostic endpoint
    app.routes.insert(0, Route("/debug/info", debug_info))

    # Add API endpoints for UI
    app.routes.insert(0, Route("/api/info", api_info))
    app.routes.insert(0, Route("/api/tools", api_tools))
    app.routes.insert(0, Route("/api/resources", api_resources))
    app.routes.insert(0, Route("/api/prompts", api_prompts))

    # Add UI static files if enabled
    ui_enabled = os.environ.get("MCP_UI_ENABLED", "true").lower() == "true"
    if ui_enabled:
        ui_dir = os.path.join(os.path.dirname(__file__), "ui")
        if os.path.isdir(ui_dir):
            from starlette.staticfiles import StaticFiles

            app.routes.append(Mount("/ui", StaticFiles(directory=ui_dir, html=True)))
            logger.info("Web UI enabled at /ui")

    # Add metrics endpoint if enabled
    if metrics_enabled():
        from metrics import get_metrics_app

        app.routes.append(Mount("/metrics", get_metrics_app()))
        logger.info("Metrics endpoint enabled at /metrics")

    # Step 9: Mark startup complete
    mark_startup_complete()

    # Step 10: Setup graceful shutdown
    def _handle_signal(signum, frame):
        logger.info("Received signal %s, shutting down...", signal.Signals(signum).name)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Step 11: Run
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8000"))

    logger.info("Listening on %s:%d%s", host, port, path)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
