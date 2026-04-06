"""Example: Multiple resources from a single file (v0.3.0).

Use the RESOURCES dict to map multiple URIs to handler functions.
This replaces the single RESOURCE_URI pattern when you need
multiple resources in one file.
"""

import json

RESOURCES = {
    "status://health": "get_health",
    "status://version": "get_version",
    "status://uptime": "get_uptime",
}


def get_health() -> str:
    """Server health status."""
    return json.dumps({"status": "healthy", "checks": {"db": "ok", "cache": "ok"}}, indent=2)


def get_version() -> str:
    """Application version."""
    return "1.0.0"


def get_uptime() -> str:
    """Server uptime information."""
    import time

    return json.dumps({"uptime_seconds": int(time.time()), "started": "2026-01-01T00:00:00Z"}, indent=2)
