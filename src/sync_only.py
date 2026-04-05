"""Standalone source sync script for init container pattern.

Runs sync_sources() and exits. Used as a Kubernetes init container
to pre-populate the workspace volume before the main server starts.

Usage:
    python /app/sync_only.py
"""

import logging
import os
import sys

from loader import sync_sources
from logging_config import configure_logging


def main() -> None:
    configure_logging()
    logger = logging.getLogger("fastmcp-server.sync")

    workspace = os.environ.get("MCP_WORKSPACE", "/app/workspace")
    logger.info("Starting source sync into %s...", workspace)

    try:
        sync_sources(workspace)
    except Exception:
        logger.exception("Source sync failed")
        sys.exit(1)

    logger.info("Source sync complete")


if __name__ == "__main__":
    main()
