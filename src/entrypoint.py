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

from loader import sync_sources
from server_builder import build_server

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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


def main() -> None:
    server_name = os.environ.get("MCP_SERVER_NAME", "fastmcp-server")
    workspace = os.environ.get("MCP_WORKSPACE", "/app/workspace")

    # Step 1: Install extra pip packages if requested
    _install_extra_packages()

    # Step 2: Sync external sources (S3, Git, Inline) into workspace
    try:
        sync_sources(workspace)
    except Exception:
        logger.exception("Failed to sync sources")
        sys.exit(1)

    # Step 3: Build FastMCP server from loaded files
    mcp, counts = build_server(workspace)

    # Step 4: Print startup banner
    _print_banner(server_name, **counts)

    # Step 5: Create HTTP app
    path = os.environ.get("MCP_PATH", "/mcp")
    app = mcp.http_app(path=path)

    # Step 6: Setup graceful shutdown
    def _handle_signal(signum, frame):
        logger.info("Received signal %s, shutting down...", signal.Signals(signum).name)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Step 7: Run
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8000"))

    logger.info("Listening on %s:%d%s", host, port, path)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
