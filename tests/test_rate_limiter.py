"""Tests for rate limiter module."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rate_limiter import _parse_rate, rate_limit_tool, reset_rate_limits


def setup_function():
    reset_rate_limits()
    os.environ.pop("MCP_RATE_LIMIT_DEFAULT", None)


def test_parse_rate_valid():
    assert _parse_rate("10/min") == (10, 60.0)
    assert _parse_rate("5/s") == (5, 1.0)
    assert _parse_rate("100/hour") == (100, 3600.0)


def test_parse_rate_invalid():
    assert _parse_rate("") is None
    assert _parse_rate("abc") is None
    assert _parse_rate("10/xyz") is None


def test_rate_limit_noop_when_no_limit():
    def my_tool() -> str:
        return "ok"

    wrapped = rate_limit_tool(my_tool, "my_tool", module_rate=None)
    assert wrapped is my_tool


def test_rate_limit_allows_within_limit():
    def my_tool() -> str:
        return "ok"

    wrapped = rate_limit_tool(my_tool, "within_limit", module_rate="5/s")
    for _ in range(5):
        assert wrapped() == "ok"


def test_rate_limit_blocks_over_limit():
    def my_tool() -> str:
        return "ok"

    wrapped = rate_limit_tool(my_tool, "over_limit", module_rate="2/s")
    assert wrapped() == "ok"
    assert wrapped() == "ok"
    result = wrapped()
    assert "Rate limit exceeded" in result


def test_rate_limit_async():
    async def my_tool() -> str:
        return "ok"

    wrapped = rate_limit_tool(my_tool, "async_limit", module_rate="1/s")
    assert asyncio.run(wrapped()) == "ok"
    result = asyncio.run(wrapped())
    assert "Rate limit exceeded" in result


def test_rate_limit_env_override():
    os.environ["MCP_RATE_LIMIT_ENVTOOL"] = "1/s"
    try:

        def my_tool() -> str:
            return "ok"

        wrapped = rate_limit_tool(my_tool, "envtool", module_rate="100/min")
        assert wrapped() == "ok"
        result = wrapped()
        assert "Rate limit exceeded" in result
    finally:
        os.environ.pop("MCP_RATE_LIMIT_ENVTOOL", None)
