"""Tests for structured logging configuration."""

import json
import logging

from logging_config import JSONFormatter, configure_logging


def test_json_formatter():
    """JSONFormatter produces valid JSON with required fields."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    output = formatter.format(record)
    data = json.loads(output)

    assert data["level"] == "INFO"
    assert data["logger"] == "test.logger"
    assert data["message"] == "Test message"
    assert "timestamp" in data


def test_json_formatter_with_extra():
    """JSONFormatter includes extra fields when present."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Tool registered",
        args=(),
        exc_info=None,
    )
    record.tool = "greet"
    record.source_file = "greet.py"

    output = formatter.format(record)
    data = json.loads(output)

    assert data["tool"] == "greet"
    assert data["source_file"] == "greet.py"


def test_configure_logging_text(monkeypatch):
    """Text format uses standard formatter."""
    monkeypatch.setenv("LOG_FORMAT", "text")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    configure_logging()

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    assert not isinstance(root.handlers[0].formatter, JSONFormatter)


def test_configure_logging_json(monkeypatch):
    """JSON format uses JSONFormatter."""
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    configure_logging()

    root = logging.getLogger()
    assert isinstance(root.handlers[0].formatter, JSONFormatter)
