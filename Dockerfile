FROM docker.io/library/python:3.13-slim AS base

LABEL org.opencontainers.image.title="fastmcp-server" \
      org.opencontainers.image.description="Proprietary FastMCP server image for the HelmForge mcp-server Helm chart" \
      org.opencontainers.image.vendor="HelmForge" \
      org.opencontainers.image.url="https://helmforge.dev" \
      org.opencontainers.image.source="https://github.com/helmforgedev/fastmcp-server"

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "fastmcp[http]==3.2.0" \
    uvicorn \
    boto3 \
    gitpython

WORKDIR /app
COPY src/ /app/

RUN adduser --disabled-password --gecos "" --uid 1000 mcpuser
USER 1000

EXPOSE 8000

ENTRYPOINT ["python", "/app/entrypoint.py"]
