"""Example: Tool with structured output using ToolResult (v0.3.0).

Tools can return ToolResult for full control over response format,
including structured JSON content and metadata.
"""

from fastmcp.tools.tool import ToolResult


def analyze(data: str) -> ToolResult:
    """Analyze input data and return structured results."""
    words = data.split()
    return ToolResult(
        content=f"Analysis complete: {len(words)} words found",
        structured_content={
            "word_count": len(words),
            "char_count": len(data),
            "unique_words": len(set(words)),
        },
        meta={"analyzer_version": "1.0"},
    )
