"""Structured logging configuration for FastMCP server.

Supports two formats via LOG_FORMAT environment variable:
  - text (default): Human-readable format
  - json: Structured JSON for log aggregation (Loki, ELK, CloudWatch, Datadog)
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone


def _secret_values() -> list[str]:
    values = []
    for key in (
        "MCP_AUTH_TOKEN",
        "SOURCE_GIT_TOKEN",
        "SOURCE_S3_ACCESS_KEY",
        "SOURCE_S3_SECRET_KEY",
        "SOURCE_OCI_PASSWORD",
        "GITHUB_TOKEN",
    ):
        value = os.environ.get(key, "")
        if value and len(value) >= 4:
            values.append(value)
    return values


def redact(value):
    """Redact known secrets and bearer credentials from log values."""
    if not isinstance(value, str):
        return value

    redacted = value
    for secret in _secret_values():
        redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(
        r"(https://)([^/\s:@]+:)?[^@\s/]+@",
        r"\1[REDACTED]@",
        redacted,
    )
    redacted = re.sub(
        r"(Bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted


class RedactingFilter(logging.Filter):
    """Apply best-effort redaction before handlers render log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: redact(value) for key, value in record.args.items()}
            else:
                record.args = tuple(redact(value) for value in record.args)
        for key in (
            "tool",
            "source_file",
            "request_id",
            "source",
            "component",
            "client_id",
            "trace_id",
            "repo",
            "branch",
            "action",
            "result",
        ):
            value = getattr(record, key, None)
            if value is not None:
                setattr(record, key, redact(value))
        return True


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields if present
        for key in (
            "tool",
            "source_file",
            "request_id",
            "source",
            "component",
            "client_id",
            "trace_id",
            "repo",
            "branch",
            "action",
            "result",
        ):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = redact(value)

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = redact(self.formatException(record.exc_info))

        return json.dumps(log_entry, default=str)


def configure_logging() -> None:
    """Configure logging based on LOG_FORMAT and LOG_LEVEL env vars."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_format = os.environ.get("LOG_FORMAT", "text").lower()

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.addFilter(RedactingFilter())

    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    root_logger.addHandler(handler)
