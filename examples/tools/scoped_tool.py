"""Example: Tool metadata.

The simplified runtime ignores tool-level scopes. Use annotations for client
hints, and put operational guardrails inside the tool implementation.
"""

__tags__ = {"admin", "devops"}
__annotations_mcp__ = {"destructiveHint": True, "title": "Deploy Service"}


def deploy(service: str, version: str) -> str:
    """Deploy a service to production."""
    return f"Deployed {service}@{version}"
