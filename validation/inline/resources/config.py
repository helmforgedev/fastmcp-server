RESOURCE_URI = "config://app"


def get_config() -> dict:
    """Application configuration."""
    return {"version": "1.0", "env": "production", "features": ["tools", "resources"]}
