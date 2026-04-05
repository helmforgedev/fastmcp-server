"""Example: LLM Sampling via Context.

Tools can call LLMs via ctx.sample() to perform AI-powered operations.
The client's LLM handles the sampling request.

Note: Sampling requires the MCP client to support it.
"""

from fastmcp import Context


async def smart_summarize(text: str, ctx: Context) -> str:
    """Summarize text using the client's LLM via sampling."""
    result = await ctx.sample(
        f"Summarize this text in 3 bullet points:\n\n{text}",
        temperature=0.3,
    )
    return result.text


async def translate(text: str, target_language: str, ctx: Context) -> str:
    """Translate text to a target language using the client's LLM."""
    result = await ctx.sample(
        f"Translate the following text to {target_language}. "
        f"Return only the translation, no explanation.\n\n{text}",
        temperature=0.1,
    )
    return result.text
