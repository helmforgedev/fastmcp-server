"""Rate limiting for tool calls.

Supports:
  - Module-level: __rate_limit__ = "10/min"
  - Per-tool env: MCP_RATE_LIMIT_<TOOL_NAME>=5/min
  - Global default: MCP_RATE_LIMIT_DEFAULT=100/min

Uses a simple sliding window counter per tool name.
"""

import functools
import inspect
import logging
import os
import threading
import time
import types

logger = logging.getLogger("fastmcp-server.rate_limiter")

_locks: dict[str, threading.Lock] = {}
_windows: dict[str, list[float]] = {}


def _parse_rate(rate_str: str) -> tuple[int, float] | None:
    """Parse rate string like '10/min' or '100/hour' into (count, window_seconds)."""
    if not rate_str:
        return None

    rate_str = rate_str.strip().lower()
    parts = rate_str.split("/")
    if len(parts) != 2:
        logger.warning("Invalid rate limit format: '%s' (expected N/unit)", rate_str)
        return None

    try:
        count = int(parts[0])
    except ValueError:
        logger.warning("Invalid rate limit count: '%s'", parts[0])
        return None

    unit = parts[1].strip()
    unit_map = {
        "s": 1.0,
        "sec": 1.0,
        "second": 1.0,
        "m": 60.0,
        "min": 60.0,
        "minute": 60.0,
        "h": 3600.0,
        "hr": 3600.0,
        "hour": 3600.0,
    }

    window = unit_map.get(unit)
    if window is None:
        logger.warning("Unknown rate limit unit: '%s'", unit)
        return None

    return (count, window)


def _get_rate_for_tool(tool_name: str, module_rate: str | None = None) -> tuple[int, float] | None:
    """Determine rate limit for a tool (env override > module-level > global default)."""
    # Per-tool env override: MCP_RATE_LIMIT_<TOOL_NAME_UPPER>
    env_key = f"MCP_RATE_LIMIT_{tool_name.upper()}"
    env_rate = os.environ.get(env_key)
    if env_rate:
        parsed = _parse_rate(env_rate)
        if parsed:
            return parsed

    # Module-level __rate_limit__
    if module_rate:
        parsed = _parse_rate(module_rate)
        if parsed:
            return parsed

    # Global default
    default_rate = os.environ.get("MCP_RATE_LIMIT_DEFAULT")
    if default_rate:
        parsed = _parse_rate(default_rate)
        if parsed:
            return parsed

    return None


def _check_rate(tool_name: str, max_count: int, window_seconds: float) -> bool:
    """Check if a tool call is within rate limits. Returns True if allowed."""
    if tool_name not in _locks:
        _locks[tool_name] = threading.Lock()

    with _locks[tool_name]:
        now = time.monotonic()
        if tool_name not in _windows:
            _windows[tool_name] = []

        # Prune expired entries
        cutoff = now - window_seconds
        _windows[tool_name] = [t for t in _windows[tool_name] if t > cutoff]

        if len(_windows[tool_name]) >= max_count:
            return False

        _windows[tool_name].append(now)
        return True


def rate_limit_tool(
    func: types.FunctionType,
    tool_name: str,
    module_rate: str | None = None,
) -> types.FunctionType:
    """Wrap a tool function with rate limiting."""
    rate = _get_rate_for_tool(tool_name, module_rate)
    if rate is None:
        return func

    max_count, window_seconds = rate
    logger.debug("Rate limiting tool '%s': %d calls per %.0fs", tool_name, max_count, window_seconds)

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        if not _check_rate(tool_name, max_count, window_seconds):
            return f"Error: Rate limit exceeded for tool '{tool_name}' ({max_count} calls per {window_seconds:.0f}s)"
        return func(*args, **kwargs)

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        if not _check_rate(tool_name, max_count, window_seconds):
            return f"Error: Rate limit exceeded for tool '{tool_name}' ({max_count} calls per {window_seconds:.0f}s)"
        return await func(*args, **kwargs)

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def reset_rate_limits() -> None:
    """Clear all rate limit state (useful for testing)."""
    _windows.clear()
    _locks.clear()
