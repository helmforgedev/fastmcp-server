"""Example: Tool-level auth scopes.

The __required_scopes__ variable declares which JWT scopes
are needed to execute this tool. The scopes are stored in
the tool's annotations for middleware enforcement.
"""

__required_scopes__ = ["deploy:write", "admin"]
__tags__ = {"admin", "devops"}


def deploy(service: str, version: str) -> str:
    """Deploy a service to production. Requires deploy:write scope."""
    return f"Deployed {service}@{version}"
