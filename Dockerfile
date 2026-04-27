# Stage 1: Install dependencies in a builder layer
FROM docker.io/library/python:3.13-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements.txt

# Stage 2: Final runtime image
FROM docker.io/library/python:3.13-slim

LABEL org.opencontainers.image.title="fastmcp-server" \
      org.opencontainers.image.description="Production-ready FastMCP server with dynamic tool loading from inline, S3, and Git sources" \
      org.opencontainers.image.vendor="HelmForge" \
      org.opencontainers.image.url="https://github.com/helmforgedev/fastmcp-server" \
      org.opencontainers.image.source="https://github.com/helmforgedev/fastmcp-server" \
      org.opencontainers.image.licenses="Apache-2.0"

# Install only runtime dependency (git for git-source sync)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user with writable home (needed for pip runtime installs)
RUN groupadd --gid 1000 mcpuser && \
    useradd --uid 1000 --gid 1000 --create-home --home-dir /home/mcpuser --shell /usr/sbin/nologin mcpuser

WORKDIR /app

# Pre-create workspace with correct ownership
RUN mkdir -p /app/workspace /app/inline && \
    chown -R 1000:1000 /app

COPY --chown=1000:1000 src/ /app/
COPY --chown=1000:1000 src/ui/ /app/ui/

USER 1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/mcp || exit 1

ENTRYPOINT ["python", "/app/entrypoint.py"]
