import json

RESOURCE_URI = "config://app"


def get_config() -> str:
    """Application configuration."""
    return json.dumps({"version": "1.0", "env": "production", "features": ["tools", "resources"]}, indent=2)
