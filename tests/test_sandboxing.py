"""Tests for tool sandboxing module."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sandboxing import _truncate_output, sandbox_tool


def test_truncate_output_within_limit():
    result = _truncate_output("hello world", 1)  # 1KB limit
    assert result == "hello world"


def test_truncate_output_exceeds_limit():
    big_text = "A" * 2048  # 2KB
    result = _truncate_output(big_text, 1)  # 1KB limit
    assert len(result.encode("utf-8")) < 2048
    assert "[output truncated at 1KB]" in result


def test_truncate_output_zero_limit():
    result = _truncate_output("hello", 0)
    assert result == "hello"


def test_sandbox_tool_noop_when_no_limits():
    def my_tool(x: str) -> str:
        return x

    wrapped = sandbox_tool(my_tool, "my_tool", max_memory_mb=0, max_output_size_kb=0)
    assert wrapped is my_tool


def test_sandbox_tool_output_truncation():
    def big_output() -> str:
        return "X" * 4096

    wrapped = sandbox_tool(big_output, "big_output", max_output_size_kb=1)
    result = wrapped()
    assert "[output truncated at 1KB]" in result


def test_sandbox_async_tool_output_truncation():
    async def big_async() -> str:
        return "Y" * 4096

    wrapped = sandbox_tool(big_async, "big_async", max_output_size_kb=1)
    result = asyncio.run(wrapped())
    assert "[output truncated at 1KB]" in result
