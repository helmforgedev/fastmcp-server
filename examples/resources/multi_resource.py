"""Example: Multiple resources from a single file (v0.3.0).

Use the RESOURCES dict to map multiple URIs to handler functions.
This replaces the single RESOURCE_URI pattern when you need
multiple resources in one file.
"""

RESOURCES = {
    "status://health": "get_health",
    "status://version": "get_version",
    "status://uptime": "get_uptime",
}


def get_health() -> dict:
    """Server health status."""
    return {"status": "healthy", "checks": {"db": "ok", "cache": "ok"}}


def get_version() -> str:
    """Application version."""
    return "1.0.0"


def get_uptime() -> dict:
    """Server uptime information."""
    import time

    return {"uptime_seconds": int(time.time()), "started": "2026-01-01T00:00:00Z"}
