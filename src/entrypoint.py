"""FastMCP Server Entrypoint.

Loads tools, resources, and prompts from multiple sources (inline, S3, Git),
builds a FastMCP server, and starts it via Uvicorn.
"""

import logging
import os
import sys

import uvicorn

from loader import sync_sources
from server_builder import build_server

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fastmcp-server")


def main() -> None:
    logger.info("Starting FastMCP server...")

    # Step 1: Sync external sources (S3, Git) into /app/workspace
    workspace = os.environ.get("MCP_WORKSPACE", "/app/workspace")
    try:
        sync_sources(workspace)
    except Exception:
        logger.exception("Failed to sync sources")
        sys.exit(1)

    # Step 2: Build FastMCP server from loaded files
    mcp = build_server(workspace)

    # Step 3: Create HTTP app
    path = os.environ.get("MCP_PATH", "/mcp")
    app = mcp.http_app(path=path)

    # Step 4: Run
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8000"))

    logger.info("Listening on %s:%d%s", host, port, path)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
