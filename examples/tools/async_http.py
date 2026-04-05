"""Example: Async tool using httpx (v0.3.0).

Async tools (async def) are natively supported. They are preferred
for I/O-bound operations like HTTP requests, database queries, etc.
Sync tools (def) automatically run in thread pools.
"""


async def fetch_url(url: str) -> str:
    """Fetch the content of a URL."""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.text[:2000]


async def check_endpoint(url: str) -> dict:
    """Check if an HTTP endpoint is reachable."""
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            response = await client.head(url, timeout=10.0)
            return {"url": url, "status": response.status_code, "reachable": True}
    except Exception as e:
        return {"url": url, "status": 0, "reachable": False, "error": str(e)}
