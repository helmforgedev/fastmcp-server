import json

RESOURCE_URI = "status://server"


def get_status() -> str:
    """Server status from S3 source."""
    return json.dumps({"source": "s3", "status": "healthy"}, indent=2)
