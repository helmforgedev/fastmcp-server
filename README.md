# fastmcp-server

Proprietary FastMCP server image for the [HelmForge](https://helmforge.dev) `mcp-server` Helm chart.

## Overview

A lightweight, production-ready Docker image that runs a [FastMCP](https://gofastmcp.dev) server with dynamic loading of tools, resources, prompts, and knowledge bases from multiple sources.

## Sources

The image supports three data sources with merge precedence (highest first):

1. **Inline** — ConfigMap-mounted files at `/app/inline/`
2. **S3** — Any S3-compatible storage (AWS S3, MinIO, Cloudflare R2)
3. **Git** — Clone from any HTTPS Git repository

## Workspace Structure

```
/app/workspace/
├── tools/        *.py files — each public function becomes an MCP tool
├── resources/    *.py files — define RESOURCE_URI + handler function
├── prompts/      *.py files — each public function becomes an MCP prompt
└── knowledge/    any files  — served as knowledge:// resources
```

## Environment Variables

### Server

| Variable | Default | Description |
|---|---|---|
| `MCP_SERVER_NAME` | `fastmcp-server` | Server display name |
| `MCP_HOST` | `0.0.0.0` | Listen address |
| `MCP_PORT` | `8000` | Listen port |
| `MCP_PATH` | `/mcp` | HTTP endpoint path |
| `MCP_WORKSPACE` | `/app/workspace` | Workspace directory |
| `LOG_LEVEL` | `INFO` | Logging level |

### Authentication

| Variable | Default | Description |
|---|---|---|
| `MCP_AUTH_TYPE` | `none` | `bearer`, `jwt`, or `none` |
| `MCP_AUTH_TOKEN` | | Bearer token value |
| `MCP_AUTH_JWT_ISSUER` | | JWT issuer |
| `MCP_AUTH_JWT_AUDIENCE` | | JWT audience |
| `MCP_AUTH_JWT_JWKS_URI` | | JWKS endpoint URL |

### S3 Source

| Variable | Default | Description |
|---|---|---|
| `SOURCE_S3_ENABLED` | `false` | Enable S3 sync |
| `SOURCE_S3_ENDPOINT` | | S3-compatible endpoint URL |
| `SOURCE_S3_BUCKET` | | Bucket name |
| `SOURCE_S3_REGION` | `us-east-1` | AWS region |
| `SOURCE_S3_PREFIX` | | Key prefix filter |
| `SOURCE_S3_ACCESS_KEY` | | Access key ID |
| `SOURCE_S3_SECRET_KEY` | | Secret access key |

### Git Source

| Variable | Default | Description |
|---|---|---|
| `SOURCE_GIT_ENABLED` | `false` | Enable Git sync |
| `SOURCE_GIT_REPOSITORY` | | Repository HTTPS URL |
| `SOURCE_GIT_BRANCH` | `main` | Branch to clone |
| `SOURCE_GIT_PATH` | | Subdirectory within the repo |
| `SOURCE_GIT_TOKEN` | | Auth token for private repos |

## Writing Tools

Create a Python file in `tools/` with public functions:

```python
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    import httpx
    return httpx.get(f"https://wttr.in/{city}?format=3").text

def roll_dice(sides: int = 6) -> int:
    """Roll a die with the given number of sides."""
    import random
    return random.randint(1, sides)
```

Every public function is automatically registered as an MCP tool.

## Writing Resources

Create a Python file in `resources/` with a `RESOURCE_URI` constant:

```python
RESOURCE_URI = "config://app"

def get_config() -> dict:
    """Application configuration."""
    return {"version": "1.0", "env": "production"}
```

## Writing Prompts

Create a Python file in `prompts/`:

```python
def summarize(text: str) -> str:
    """Summarize the provided text."""
    return f"Please provide a concise summary of:\n\n{text}"
```

## License

Proprietary — HelmForge
