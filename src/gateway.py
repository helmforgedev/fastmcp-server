"""Gateway mode — mount remote MCP servers as proxies.

Mounts remote MCP servers into the local FastMCP instance via
FastMCP's proxy/mount capabilities. Tools from remote servers
are namespaced automatically.

Environment variables:
  MCP_MODE           — server (default) or gateway
  MCP_MOUNT_SERVERS  — JSON array of {name, url, namespace} objects
"""

import json
import logging
import os

logger = logging.getLogger("fastmcp-server.gateway")


def get_mount_config() -> list[dict]:
    """Parse MCP_MOUNT_SERVERS environment variable."""
    raw = os.environ.get("MCP_MOUNT_SERVERS", "")
    if not raw:
        return []
    try:
        servers = json.loads(raw)
        if not isinstance(servers, list):
            logger.error("MCP_MOUNT_SERVERS must be a JSON array")
            return []
        return servers
    except json.JSONDecodeError:
        logger.exception("Failed to parse MCP_MOUNT_SERVERS")
        return []


def is_gateway_mode() -> bool:
    """Check if running in gateway mode."""
    return os.environ.get("MCP_MODE", "server").lower() == "gateway"


async def mount_remote_servers(mcp) -> list[dict]:
    """Mount remote MCP servers via FastMCP proxy.

    Returns list of mounted server info dicts.
    """
    servers = get_mount_config()
    if not servers:
        return []

    mounted = []
    for server_cfg in servers:
        name = server_cfg.get("name", "")
        url = server_cfg.get("url", "")
        namespace = server_cfg.get("namespace", name)

        if not name or not url:
            logger.warning(
                "Skipping mount config with missing name or url: %s", server_cfg
            )
            continue

        try:
            from fastmcp import Client
            from fastmcp.client.transports import StreamableHttpTransport

            transport = StreamableHttpTransport(url)
            client = Client(transport=transport)
            proxy = await mcp.as_proxy(client)

            # Mount with namespace prefix
            mcp.mount(proxy, namespace=namespace)

            info = {
                "name": name,
                "url": url,
                "namespace": namespace,
                "status": "mounted",
            }
            mounted.append(info)
            logger.info("Mounted remote server: %s (%s) as /%s", name, url, namespace)
        except Exception:
            logger.exception("Failed to mount remote server: %s (%s)", name, url)
            mounted.append(
                {
                    "name": name,
                    "url": url,
                    "namespace": namespace,
                    "status": "error",
                }
            )

    return mounted
