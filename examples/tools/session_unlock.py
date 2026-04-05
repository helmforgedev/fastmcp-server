"""Example: Per-session visibility via Context.

Tools tagged 'admin' are hidden by default. This tool unlocks them
for the current session when the correct password is provided.

Usage:
  MCP_DISABLE_TAGS=admin  (hides admin tools by default)
"""

import os

from fastmcp import Context

__tags__ = {"public"}

ADMIN_PASSWORD = os.environ.get("ADMIN_TOOL_PASSWORD", "admin123")


async def unlock_admin_tools(password: str, ctx: Context) -> str:
    """Unlock admin tools for this session."""
    if password == ADMIN_PASSWORD:
        await ctx.enable_components(tags={"admin"})
        return "Admin tools unlocked for this session"
    return "Invalid password"
