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
from authz import HttpAuthMiddleware
from health import (
    healthz,
    mark_components_loaded,
    mark_sources_synced,
    mark_startup_complete,
    readyz,
    startupz,
)
from gateway import is_gateway_mode, mount_remote_servers
from hot_reload import start_watcher
from loader import sync_sources
from logging_config import configure_logging
from metrics import init_metrics, is_enabled as metrics_enabled, set_component_counts
from periodic_sync import start_periodic_sync
from reload_endpoint import init_reload, reload_endpoint
from server_builder import build_server, rebuild_components
from visibility import apply_visibility

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

    # Step 2b: Auto-discover and install pip tool packages
    from package_discovery import discover_tool_packages, install_discovered_tools

    discovered_packages = discover_tool_packages()
    if discovered_packages:
        pkg_count = install_discovered_tools(workspace, discovered_packages)
        logger.info("Auto-installed %d tools from pip packages", pkg_count)

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

    # Step 5: Apply visibility rules
    apply_visibility(mcp)

    # Step 6: Mount remote servers (gateway mode)
    mounted_servers = []
    if is_gateway_mode():
        import asyncio

        mounted_servers = asyncio.run(mount_remote_servers(mcp))
        logger.info("Gateway mode: %d remote server(s) mounted", len(mounted_servers))

    # Step 7: Print startup banner
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

    # Derive base path for mounting related routes
    # e.g. /helmforge/mcp -> /helmforge, /mcp -> ""
    base_path = path.rsplit("/", 1)[0]

    # Health probes at root (accessed by kubelet, not through ingress)
    app.routes.insert(0, Route("/healthz", healthz))
    app.routes.insert(0, Route("/readyz", readyz))
    app.routes.insert(0, Route("/startupz", startupz))

    # Diagnostic endpoint under base path
    app.routes.insert(0, Route(f"{base_path}/debug/info", debug_info))

    # API endpoints for UI under base path
    app.routes.insert(0, Route(f"{base_path}/api/info", api_info))
    app.routes.insert(0, Route(f"{base_path}/api/tools", api_tools))
    app.routes.insert(0, Route(f"{base_path}/api/resources", api_resources))
    app.routes.insert(0, Route(f"{base_path}/api/prompts", api_prompts))

    # UI static files under base path
    ui_enabled = os.environ.get("MCP_UI_ENABLED", "true").lower() == "true"
    if ui_enabled:
        ui_dir = os.path.join(os.path.dirname(__file__), "ui")
        if os.path.isdir(ui_dir):
            from starlette.staticfiles import StaticFiles

            ui_path = f"{base_path}/ui"
            app.routes.append(Mount(ui_path, StaticFiles(directory=ui_dir, html=True)))
            logger.info("Web UI enabled at %s", ui_path)

    # Reload endpoint under base path
    init_reload(mcp, workspace, sync_sources, rebuild_components)
    app.routes.insert(
        0, Route(f"{base_path}/reload", reload_endpoint, methods=["POST"])
    )

    # Metrics endpoint under base path
    if metrics_enabled():
        from metrics import get_metrics_app

        metrics_path = f"{base_path}/metrics"
        app.routes.append(Mount(metrics_path, get_metrics_app()))
        logger.info("Metrics endpoint enabled at %s", metrics_path)

    protected_prefixes = [
        f"{base_path}/debug/info",
        f"{base_path}/api",
        f"{base_path}/reload",
    ]
    if ui_enabled:
        protected_prefixes.append(f"{base_path}/ui")
    if metrics_enabled():
        protected_prefixes.append(f"{base_path}/metrics")
    app.add_middleware(HttpAuthMiddleware, protected_prefixes=protected_prefixes)

    cors_origins = [
        origin.strip()
        for origin in os.environ.get("MCP_CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if cors_origins:
        from starlette.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id"],
            allow_credentials=True,
        )
        logger.info("CORS enabled for %d configured origin(s)", len(cors_origins))

    # Step 9: Start hot reload watcher if enabled
    start_watcher(mcp, workspace, rebuild_components)

    # Step 10: Start periodic sync if configured
    start_periodic_sync(workspace, sync_sources, rebuild_components, mcp)

    # Step 11: Mark startup complete
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
