"""Example: Resource with URI template (v0.3.0).

URI templates use {param} placeholders. FastMCP automatically
generates a resource template that clients can discover and
request with specific parameter values.
"""

import json

RESOURCE_URI = "users://{user_id}/profile"


def get_profile(user_id: str) -> str:
    """Get user profile by ID."""
    return json.dumps({
        "user_id": user_id,
        "name": f"User {user_id}",
        "email": f"user-{user_id}@example.com",
    }, indent=2)
