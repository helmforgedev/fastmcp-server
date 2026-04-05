"""Tool sandboxing — resource limits for tool execution.

Supports module-level magic variables:
  __max_memory_mb__ = 256       # Memory limit (soft, via resource module on Linux)
  __max_output_size_kb__ = 100  # Truncate output if exceeds limit

On Linux, uses resource.setrlimit for memory enforcement.
On other platforms, memory limiting is best-effort (logged warning only).
"""

import functools
import inspect
import logging
import os
import platform
import types

logger = logging.getLogger("fastmcp-server.sandboxing")

# Default limits from environment
DEFAULT_MAX_MEMORY_MB = int(os.environ.get("MCP_MAX_MEMORY_MB", "0"))
DEFAULT_MAX_OUTPUT_SIZE_KB = int(os.environ.get("MCP_MAX_OUTPUT_SIZE_KB", "0"))


def _truncate_output(result: str, max_kb: int) -> str:
    """Truncate tool output if it exceeds max_kb kilobytes."""
    if max_kb <= 0:
        return result
    max_bytes = max_kb * 1024
    encoded = result.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return result
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return truncated + f"\n... [output truncated at {max_kb}KB]"


def _set_memory_limit(max_mb: int) -> None:
    """Set soft memory limit for current process (Linux only)."""
    if max_mb <= 0:
        return
    if platform.system() != "Linux":
        return
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        new_soft = max_mb * 1024 * 1024
        if hard != resource.RLIM_INFINITY and new_soft > hard:
            new_soft = hard
        resource.setrlimit(resource.RLIMIT_AS, (new_soft, hard))
    except (ImportError, ValueError, OSError) as exc:
        logger.warning("Could not set memory limit to %dMB: %s", max_mb, exc)


def _restore_memory_limit(original_soft: int, original_hard: int) -> None:
    """Restore original memory limit."""
    if platform.system() != "Linux":
        return
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (original_soft, original_hard))
    except (ImportError, ValueError, OSError):
        pass


def _get_original_limits() -> tuple[int, int]:
    """Get current memory limits."""
    if platform.system() != "Linux":
        return (0, 0)
    try:
        import resource

        return resource.getrlimit(resource.RLIMIT_AS)
    except (ImportError, ValueError, OSError):
        return (0, 0)


def sandbox_tool(
    func: types.FunctionType,
    tool_name: str,
    max_memory_mb: int = 0,
    max_output_size_kb: int = 0,
) -> types.FunctionType:
    """Wrap a tool function with sandboxing (memory + output limits)."""
    mem_limit = max_memory_mb or DEFAULT_MAX_MEMORY_MB
    output_limit = max_output_size_kb or DEFAULT_MAX_OUTPUT_SIZE_KB

    if mem_limit <= 0 and output_limit <= 0:
        return func

    logger.debug(
        "Sandboxing tool '%s': memory=%dMB, output=%dKB",
        tool_name,
        mem_limit,
        output_limit,
    )

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        original = _get_original_limits()
        try:
            _set_memory_limit(mem_limit)
            result = func(*args, **kwargs)
            if isinstance(result, str) and output_limit > 0:
                result = _truncate_output(result, output_limit)
            return result
        except MemoryError:
            logger.error("Tool '%s' exceeded memory limit of %dMB", tool_name, mem_limit)
            return f"Error: Tool '{tool_name}' exceeded memory limit ({mem_limit}MB)"
        finally:
            if mem_limit > 0:
                _restore_memory_limit(*original)

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        original = _get_original_limits()
        try:
            _set_memory_limit(mem_limit)
            result = await func(*args, **kwargs)
            if isinstance(result, str) and output_limit > 0:
                result = _truncate_output(result, output_limit)
            return result
        except MemoryError:
            logger.error("Tool '%s' exceeded memory limit of %dMB", tool_name, mem_limit)
            return f"Error: Tool '{tool_name}' exceeded memory limit ({mem_limit}MB)"
        finally:
            if mem_limit > 0:
                _restore_memory_limit(*original)

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper
