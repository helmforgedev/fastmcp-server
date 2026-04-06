"""Caching layer for idempotent tools.

Tools with __cache_ttl__ (seconds) will have their results cached
in memory using a simple TTL-based cache keyed by arguments.

Usage in tool module:
  __cache_ttl__ = 300  # cache results for 5 minutes

Environment:
  MCP_CACHE_ENABLED=true   # enable/disable caching globally (default: true)
  MCP_CACHE_MAX_SIZE=1000  # max entries per tool cache (default: 1000)
"""

import functools
import hashlib
import inspect
import json
import logging
import os
import threading
import time
import types

logger = logging.getLogger("fastmcp-server.caching")

_caches: dict[str, dict] = {}
_locks: dict[str, threading.Lock] = {}

MAX_CACHE_SIZE = int(os.environ.get("MCP_CACHE_MAX_SIZE", "1000"))


def _is_cache_enabled() -> bool:
    return os.environ.get("MCP_CACHE_ENABLED", "true").lower() != "false"


def _make_cache_key(args: tuple, kwargs: dict) -> str:
    """Create a deterministic cache key from function arguments."""
    try:
        key_data = json.dumps(
            {
                "a": [repr(a) for a in args],
                "k": {k: repr(v) for k, v in sorted(kwargs.items())},
            },
            sort_keys=True,
        )
    except (TypeError, ValueError):
        key_data = repr((args, kwargs))
    return hashlib.md5(key_data.encode()).hexdigest()


def _get_cached(tool_name: str, key: str, ttl: float) -> tuple[bool, object]:
    """Get cached result. Returns (hit, value)."""
    if tool_name not in _caches:
        return (False, None)

    if tool_name not in _locks:
        _locks[tool_name] = threading.Lock()

    with _locks[tool_name]:
        entry = _caches[tool_name].get(key)
        if entry is None:
            return (False, None)
        if time.monotonic() - entry["time"] > ttl:
            del _caches[tool_name][key]
            return (False, None)
        return (True, entry["value"])


def _set_cached(tool_name: str, key: str, value: object) -> None:
    """Store a result in cache."""
    if tool_name not in _locks:
        _locks[tool_name] = threading.Lock()
    if tool_name not in _caches:
        _caches[tool_name] = {}

    with _locks[tool_name]:
        # Evict oldest if over limit
        if len(_caches[tool_name]) >= MAX_CACHE_SIZE:
            oldest_key = min(
                _caches[tool_name], key=lambda k: _caches[tool_name][k]["time"]
            )
            del _caches[tool_name][oldest_key]

        _caches[tool_name][key] = {"value": value, "time": time.monotonic()}


def cache_tool(
    func: types.FunctionType,
    tool_name: str,
    ttl: float,
) -> types.FunctionType:
    """Wrap a tool function with TTL-based caching."""
    if ttl <= 0 or not _is_cache_enabled():
        return func

    logger.debug("Caching tool '%s' with TTL=%ds", tool_name, ttl)

    # Initialize lock for this tool
    _locks[tool_name] = threading.Lock()
    _caches[tool_name] = {}

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        key = _make_cache_key(args, kwargs)
        hit, value = _get_cached(tool_name, key, ttl)
        if hit:
            logger.debug("Cache hit for tool '%s' key=%s", tool_name, key[:8])
            return value
        result = func(*args, **kwargs)
        _set_cached(tool_name, key, result)
        return result

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        key = _make_cache_key(args, kwargs)
        hit, value = _get_cached(tool_name, key, ttl)
        if hit:
            logger.debug("Cache hit for tool '%s' key=%s", tool_name, key[:8])
            return value
        result = await func(*args, **kwargs)
        _set_cached(tool_name, key, result)
        return result

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def clear_cache(tool_name: str | None = None) -> None:
    """Clear cache for a specific tool or all tools."""
    if tool_name:
        if tool_name in _caches:
            _caches[tool_name].clear()
    else:
        for cache in _caches.values():
            cache.clear()


def get_cache_stats() -> dict:
    """Get cache statistics for diagnostics."""
    stats = {}
    for tool_name, cache in _caches.items():
        stats[tool_name] = {"entries": len(cache)}
    return stats
