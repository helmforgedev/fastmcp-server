"""Example: Session state via Context.

Tools can store and retrieve session-scoped state using the Context object.
State persists for the duration of a client connection.
"""

from fastmcp import Context


async def set_preference(key: str, value: str, ctx: Context) -> str:
    """Set a user preference for this session."""
    await ctx.set_state(f"pref:{key}", value)
    return f"Preference '{key}' set to '{value}'"


async def get_preference(key: str, ctx: Context) -> str:
    """Get a user preference from this session."""
    value = await ctx.get_state(f"pref:{key}")
    if value is None:
        return f"Preference '{key}' not set"
    return f"{key} = {value}"


async def remember(key: str, value: str, ctx: Context) -> str:
    """Remember a value for later use in this session."""
    await ctx.set_state(f"memory:{key}", value)
    return f"Remembered: {key}"


async def recall(key: str, ctx: Context) -> str:
    """Recall a previously remembered value."""
    value = await ctx.get_state(f"memory:{key}")
    if value is None:
        return f"Nothing remembered for '{key}'"
    return str(value)
