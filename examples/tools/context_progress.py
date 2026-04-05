"""Example: Using Context for progress reporting and resource access.

Tools can accept a `ctx: Context` parameter to access FastMCP features:
- ctx.info() / ctx.warning() — send log messages to the client
- ctx.report_progress() — report progress to the client
- ctx.read_resource() — read another registered resource
"""

from fastmcp import Context


async def analyze_data(uri: str, ctx: Context) -> str:
    """Analyze data from a resource with progress reporting."""
    await ctx.info("Starting analysis...")

    # Read data from another resource
    data = await ctx.read_resource(uri)

    await ctx.report_progress(progress=50, total=100)

    # Process the data
    content = str(data)
    word_count = len(content.split())
    line_count = content.count("\n") + 1

    await ctx.report_progress(progress=100, total=100)
    await ctx.info("Analysis complete")

    return f"Analyzed {uri}: {word_count} words, {line_count} lines"
