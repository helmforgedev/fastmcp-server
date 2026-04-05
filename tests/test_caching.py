"""Tests for caching module."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from caching import cache_tool, clear_cache, get_cache_stats


def setup_function():
    clear_cache()


def test_cache_noop_when_zero_ttl():
    def my_tool() -> str:
        return "ok"

    wrapped = cache_tool(my_tool, "noop_tool", ttl=0)
    assert wrapped is my_tool


def test_cache_returns_cached_result():
    call_count = 0

    def my_tool(x: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{x}"

    wrapped = cache_tool(my_tool, "cached_tool", ttl=300)
    assert wrapped("a") == "result-a"
    assert wrapped("a") == "result-a"
    assert call_count == 1  # Second call served from cache


def test_cache_different_args_different_entries():
    call_count = 0

    def my_tool(x: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{x}"

    wrapped = cache_tool(my_tool, "diff_args", ttl=300)
    wrapped("a")
    wrapped("b")
    assert call_count == 2


def test_cache_async():
    call_count = 0

    async def my_tool(x: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{x}"

    wrapped = cache_tool(my_tool, "async_cached", ttl=300)
    assert asyncio.run(wrapped("a")) == "result-a"
    assert asyncio.run(wrapped("a")) == "result-a"
    assert call_count == 1


def test_cache_stats():
    def my_tool(x: str) -> str:
        return x

    wrapped = cache_tool(my_tool, "stats_tool", ttl=300)
    wrapped("hello")

    stats = get_cache_stats()
    assert "stats_tool" in stats
    assert stats["stats_tool"]["entries"] == 1


def test_clear_cache():
    def my_tool(x: str) -> str:
        return x

    wrapped = cache_tool(my_tool, "clear_tool", ttl=300)
    wrapped("hello")
    clear_cache("clear_tool")

    stats = get_cache_stats()
    assert stats["clear_tool"]["entries"] == 0
