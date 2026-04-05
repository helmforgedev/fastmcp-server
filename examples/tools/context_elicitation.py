"""Example: Elicitation — asking the user for input during tool execution.

Tools can use ctx.elicit() to ask the user for confirmation or additional
input before proceeding with an action.

Note: Elicitation requires the MCP client to support it.
"""

from fastmcp import Context


async def deploy(service: str, version: str, ctx: Context) -> str:
    """Deploy a service with user confirmation."""
    result = await ctx.elicit(
        f"Deploy {service}@{version} to production?",
        response_type=None,  # simple yes/no
    )

    if result.action != "accept":
        return "Deployment cancelled by user"

    return f"Deployed {service}@{version} to production"


async def delete_data(table: str, ctx: Context) -> str:
    """Delete data with double confirmation."""
    result = await ctx.elicit(
        f"WARNING: This will delete all data in '{table}'. Continue?",
        response_type=None,
    )

    if result.action != "accept":
        return "Deletion cancelled"

    return f"Deleted all data in {table}"
