"""Tests for tag-based visibility control."""

from visibility import _parse_tags


def test_parse_tags_empty():
    """Empty string returns empty set."""
    assert _parse_tags("") == set()


def test_parse_tags_single():
    """Single tag parsed correctly."""
    assert _parse_tags("production") == {"production"}


def test_parse_tags_multiple():
    """Multiple tags parsed correctly."""
    assert _parse_tags("production,public,v2") == {"production", "public", "v2"}


def test_parse_tags_whitespace():
    """Tags with whitespace are trimmed."""
    assert _parse_tags(" prod , public ") == {"prod", "public"}


def test_parse_tags_empty_values():
    """Empty values between commas are skipped."""
    assert _parse_tags("prod,,public,") == {"prod", "public"}
