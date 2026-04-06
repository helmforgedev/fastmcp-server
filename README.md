# fastmcp-server

Production-ready [FastMCP](https://gofastmcp.dev) server image with dynamic loading of tools, resources, prompts, and knowledge bases from multiple sources.

Run your own MCP server anywhere — Docker, Compose, Swarm, Kubernetes, or any container runtime. Define tools in Python, mount them, and your server is live.

## Quick Start

```bash
# Create a tool
mkdir -p tools
cat > tools/hello.py << 'EOF'
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"
EOF

# Run the server
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/tools:/app/inline/tools \
  docker.io/helmforge/fastmcp-server:0.4.0
```

Your MCP server is now available at `http://localhost:8000/mcp`.
The built-in Web UI is at `http://localhost:8000/ui`.

## How It Works

The server loads MCP components (tools, resources, prompts, knowledge) from a workspace directory. On startup, it syncs files from one or more sources into the workspace, registers everything with FastMCP, and exposes the server over HTTP.

```
Sources (Inline, S3, Git)
        │
        ▼
  /app/workspace/
  ├── tools/*.py         → registered as MCP tools
  ├── resources/*.py     → registered as MCP resources
  ├── prompts/*.py       → registered as MCP prompts
  └── knowledge/*        → served as knowledge:// resources
        │
        ▼
  FastMCP Server (:8000/mcp)
  ├── /ui               → Web dashboard
  ├── /healthz          → Liveness probe
  ├── /readyz           → Readiness probe
  ├── /startupz         → Startup probe
  ├── /debug/info       → Server diagnostics
  ├── /metrics          → Prometheus metrics (opt-in)
  └── /api/*            → JSON API for UI
```

## Sources

The image supports three data sources with merge precedence (highest first):

| Source | Best For | Limit |
|---|---|---|
| **Inline** (volume mount at `/app/inline/`) | Quick setup, small configs | Host filesystem |
| **S3** (AWS S3, MinIO, Cloudflare R2) | Teams, CI/CD pipelines, large knowledge bases | Unlimited |
| **Git** (any HTTPS repo) | Version-controlled tools, collaboration | Repo size |

All sources can be combined. Inline always wins on conflicts.

## Running with Docker Compose

```yaml
services:
  mcp-server:
    image: docker.io/helmforge/fastmcp-server:0.4.0
    ports:
      - "8000:8000"
    volumes:
      - ./tools:/app/inline/tools
      - ./resources:/app/inline/resources
      - ./prompts:/app/inline/prompts
      - ./knowledge:/app/inline/knowledge
    environment:
      MCP_SERVER_NAME: my-mcp-server
      MCP_AUTH_TYPE: bearer
      MCP_AUTH_TOKEN: ${MCP_AUTH_TOKEN}
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
```

## Running with S3 (MinIO example)

```yaml
services:
  mcp-server:
    image: docker.io/helmforge/fastmcp-server:0.4.0
    ports:
      - "8000:8000"
    environment:
      SOURCE_S3_ENABLED: "true"
      SOURCE_S3_ENDPOINT: http://minio:9000
      SOURCE_S3_BUCKET: mcp-tools
      SOURCE_S3_ACCESS_KEY: minioadmin
      SOURCE_S3_SECRET_KEY: minioadmin

  minio:
    image: docker.io/minio/minio:RELEASE.2025-04-03T14-56-28Z
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
```

## Running with Git Source

```bash
docker run -d \
  -p 8000:8000 \
  -e SOURCE_GIT_ENABLED=true \
  -e SOURCE_GIT_REPOSITORY=https://github.com/myorg/mcp-tools.git \
  -e SOURCE_GIT_BRANCH=main \
  docker.io/helmforge/fastmcp-server:0.4.0
```

For private repos, set `SOURCE_GIT_TOKEN` with a personal access token.

## Writing Tools

Create a `.py` file in `tools/`. Every public function becomes an MCP tool:

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

### Tool Metadata

Add optional module-level variables to control tool registration:

```python
__tags__ = {"devops", "production"}        # Categorization tags
__timeout__ = 30.0                          # Execution timeout (seconds)
__annotations_mcp__ = {                     # MCP behavior hints
    "destructiveHint": True,
    "title": "Deploy Service"
}

def deploy(service: str, version: str) -> str:
    """Deploy a service to production."""
    return f"Deployed {service}@{version}"
```

### Async Tools

Both `async def` and `def` functions work. Async is preferred for I/O-bound operations:

```python
async def fetch_url(url: str) -> str:
    """Fetch content from a URL."""
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.text
```

### Structured Output

Return `ToolResult` for full control over response format:

```python
from fastmcp.tools.tool import ToolResult

def analyze(data: str) -> ToolResult:
    """Analyze data with structured output."""
    return ToolResult(
        content="Analysis complete",
        structured_content={"word_count": len(data.split())},
        meta={"version": "1.0"}
    )
```

## Writing Resources

Create a `.py` file in `resources/` with a `RESOURCE_URI` constant and a handler function:

```python
import json

RESOURCE_URI = "config://app"

def get_config() -> str:
    """Application configuration."""
    return json.dumps({"version": "1.0", "env": "production"}, indent=2)
```

> **Important:** Resource handlers must return `str`, `bytes`, or `list[ResourceContent]`. Returning a `dict` directly will cause a serialization error.

### Resource Templates

Use `{param}` placeholders in URIs for parameterized resources:

```python
import json

RESOURCE_URI = "users://{user_id}/profile"

def get_profile(user_id: str) -> str:
    """Get user profile by ID."""
    return json.dumps({"user_id": user_id, "name": f"User {user_id}"}, indent=2)
```

### Multiple Resources per File

Use a `RESOURCES` dict to register multiple resources from one file:

```python
import json

RESOURCES = {
    "status://health": "get_health",
    "status://version": "get_version",
}

def get_health() -> str:
    return json.dumps({"status": "ok"}, indent=2)

def get_version() -> str:
    return "1.0.0"
```

## Writing Prompts

Create a `.py` file in `prompts/`. Every public function becomes an MCP prompt:

```python
def summarize(text: str) -> str:
    """Summarize the provided text."""
    return f"Please provide a concise summary of:\n\n{text}"
```

## Knowledge Base

Any file placed in `knowledge/` is served as a `knowledge://` resource. Supports text, markdown, JSON, YAML, or any UTF-8 file.

```
knowledge/
├── product-overview.md
├── api-reference.json
└── troubleshooting/
    ├── common-errors.md
    └── faq.md
```

These become accessible as `knowledge://product-overview.md`, `knowledge://troubleshooting/common-errors.md`, etc.

## Authentication

| Type | Variables | Use Case |
|---|---|---|
| None | `MCP_AUTH_TYPE=none` | Development, internal networks |
| Bearer | `MCP_AUTH_TYPE=bearer` + `MCP_AUTH_TOKEN` | API keys, service accounts |
| JWT | `MCP_AUTH_TYPE=jwt` + `MCP_AUTH_JWT_*` | OAuth/OIDC, enterprise SSO |

## Web UI

The embedded dashboard at `/ui` provides:

- **Dashboard** — Server name, version, uptime, component counts, source status
- **Tools Explorer** — All registered tools with descriptions, parameters, tags, timeout
- **Resources Explorer** — Resources and templates with URIs, MIME types
- **Prompts Explorer** — All prompts with descriptions

Auto-refreshes every 15 seconds. Disable with `MCP_UI_ENABLED=false`.

## Observability

### Health Endpoints

| Endpoint | Purpose | When 200 |
|---|---|---|
| `GET /healthz` | Liveness | Always (process is running) |
| `GET /readyz` | Readiness | Sources synced + components loaded |
| `GET /startupz` | Startup | Full initialization complete |

### Diagnostics

`GET /debug/info` returns full server diagnostics: version, FastMCP version, uptime, component details, source status, auth type, and configuration.

### Prometheus Metrics

Enable with `MCP_METRICS_ENABLED=true`. Exposes at `/metrics`:

- `mcp_tools_total` — Number of registered tools
- `mcp_resources_total` — Number of registered resources
- `mcp_prompts_total` — Number of registered prompts
- `mcp_knowledge_total` — Number of knowledge files
- `mcp_tool_calls_total{tool}` — Tool invocation counter
- `mcp_tool_duration_seconds{tool}` — Tool execution duration histogram
- `mcp_tool_errors_total{tool}` — Tool error counter
- `mcp_sources_sync_total{source,status}` — Source sync operations
- `mcp_auth_requests_total{result}` — Auth attempt counter

### Structured Logging

Set `LOG_FORMAT=json` for JSON-structured logs compatible with Loki, ELK, CloudWatch, and Datadog:

```json
{
  "timestamp": "2026-04-05T10:30:00+00:00",
  "level": "INFO",
  "logger": "fastmcp-server.builder",
  "message": "Registered tool: greet"
}
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
| `LOG_FORMAT` | `text` | Log format: `text` or `json` |
| `MCP_MASK_ERROR_DETAILS` | `false` | Hide internal error details from clients |
| `MCP_ON_DUPLICATE_TOOLS` | `warn` | Duplicate handling: `warn`, `error`, `replace`, `ignore` |
| `MCP_STRICT_LOADING` | `false` | Fail on boot if any tool/resource has errors |
| `MCP_UI_ENABLED` | `true` | Enable built-in Web UI at `/ui` |
| `MCP_METRICS_ENABLED` | `false` | Enable Prometheus metrics at `/metrics` |
| `EXTRA_PIP_PACKAGES` | | Comma-separated pip packages to install at startup |

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

## Init Container Pattern

For Kubernetes, separate source syncing from server startup using `sync_only.py`:

```bash
python /app/sync_only.py
```

This script runs `sync_sources()` and exits. Use it as a Kubernetes init container to pre-populate the workspace volume before the main server starts.

## Deployment Options

| Method | Docs |
|---|---|
| Docker / Docker Compose / Swarm | This README |
| Kubernetes (Helm) | [helmforge/charts — fastmcp-server](https://helmforge.dev) |

## Connecting MCP Clients

Once your FastMCP server is running and accessible, connect AI assistants to it as an MCP server.

### Claude Code

Add the server to your Claude Code settings (`~/.claude/settings.json` or project `.claude/settings.json`):

```json
{
  "mcpServers": {
    "my-mcp-server": {
      "type": "streamable-http",
      "url": "https://mcp.example.com/mcp"
    }
  }
}
```

With bearer authentication:

```json
{
  "mcpServers": {
    "my-mcp-server": {
      "type": "streamable-http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <your-token>"
      }
    }
  }
}
```

### Codex (VS Code Extension)

Add to your Codex configuration file (`~/.codex/config.toml`):

```toml
[mcp_servers.my-mcp-server]
enabled = true
url = "https://mcp.example.com/mcp"

[mcp_servers.my-mcp-server.http_headers]
Authorization = "Bearer <your-token>"
```

Without authentication (development):

```toml
[mcp_servers.my-mcp-server]
enabled = true
url = "https://mcp.example.com/mcp"
```

### Local Development

When running locally with Docker, use `http://localhost:8000/mcp` as the URL and omit authentication headers if `MCP_AUTH_TYPE=none`.

## License

MIT — see [LICENSE](LICENSE).
