RESOURCE_URI = "status://server"


def get_status() -> dict:
    """Server status from S3 source."""
    return {"source": "s3", "status": "healthy"}
