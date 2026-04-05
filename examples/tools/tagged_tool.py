"""Example: Tool with metadata (v0.3.0).

Module-level variables control how tools are registered:
  __tags__            - Set of string tags for categorization and filtering
  __timeout__         - Execution timeout in seconds
  __annotations_mcp__ - MCP behavior hints (readOnlyHint, destructiveHint, etc.)
"""

__tags__ = {"devops", "production"}
__timeout__ = 30.0
__annotations_mcp__ = {"destructiveHint": True, "title": "Deploy Service"}


def deploy(service: str, version: str = "latest") -> str:
    """Deploy a service to the target environment."""
    return f"Deployed {service}@{version}"


def rollback(service: str) -> str:
    """Rollback a service to the previous version."""
    return f"Rolled back {service}"
