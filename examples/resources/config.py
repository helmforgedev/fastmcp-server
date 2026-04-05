RESOURCE_URI = "config://app"


def get_config() -> dict:
    """Application configuration."""
    return {
        "version": "1.0",
        "environment": "production",
        "features": ["tools", "resources", "prompts", "knowledge"],
    }
