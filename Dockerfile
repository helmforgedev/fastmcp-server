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
      org.opencontainers.image.description="Proprietary FastMCP server image for the HelmForge mcp-server Helm chart" \
      org.opencontainers.image.vendor="HelmForge" \
      org.opencontainers.image.url="https://helmforge.dev" \
      org.opencontainers.image.source="https://github.com/helmforgedev/fastmcp-server" \
      org.opencontainers.image.licenses="MIT"

# Install only runtime dependency (git for git-source sync)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user before copying app files
RUN groupadd --gid 1000 mcpuser && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin mcpuser

WORKDIR /app

# Pre-create workspace with correct ownership
RUN mkdir -p /app/workspace /app/inline && \
    chown -R 1000:1000 /app

COPY --chown=1000:1000 src/ /app/

USER 1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/mcp || exit 1

ENTRYPOINT ["python", "/app/entrypoint.py"]
