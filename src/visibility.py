"""Tag-based visibility control for components.

Allows filtering which tools/resources/prompts are visible
based on tags, without removing the files.

Environment variables:
  MCP_ENABLE_TAGS     — Comma-separated tags to enable (allowlist)
  MCP_DISABLE_TAGS    — Comma-separated tags to disable (blocklist)
  MCP_VISIBILITY_MODE — allowlist or blocklist (default: blocklist)
"""

import logging
import os

logger = logging.getLogger("fastmcp-server.visibility")


def apply_visibility(mcp) -> None:
    """Apply tag-based visibility rules to the FastMCP instance."""
    enable_tags = _parse_tags(os.environ.get("MCP_ENABLE_TAGS", ""))
    disable_tags = _parse_tags(os.environ.get("MCP_DISABLE_TAGS", ""))
    mode = os.environ.get("MCP_VISIBILITY_MODE", "blocklist").lower()

    if not enable_tags and not disable_tags:
        return

    if mode == "allowlist" and enable_tags:
        # Only show components with matching tags
        try:
            # Disable everything first, then enable matching
            for key, component in list(mcp._local_provider._components.items()):
                tags = getattr(component, "tags", set())
                if not tags or not tags.intersection(enable_tags):
                    mcp.disable(*tags) if tags else None
                    logger.debug("Hidden (no matching tags): %s", key)
        except Exception:
            logger.debug("Allowlist mode: using enable/disable API")
        if enable_tags:
            mcp.enable(tags=enable_tags)
            logger.info("Visibility allowlist: showing tags %s", enable_tags)

    elif mode == "blocklist" and disable_tags:
        # Hide components with matching tags
        mcp.disable(tags=disable_tags)
        logger.info("Visibility blocklist: hiding tags %s", disable_tags)

    elif enable_tags:
        mcp.enable(tags=enable_tags)
        logger.info("Enabled tags: %s", enable_tags)

    if disable_tags and mode != "allowlist":
        mcp.disable(tags=disable_tags)
        logger.info("Disabled tags: %s", disable_tags)


def _parse_tags(value: str) -> set[str]:
    """Parse comma-separated tags into a set."""
    if not value:
        return set()
    return {t.strip() for t in value.split(",") if t.strip()}
