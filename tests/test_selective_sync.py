"""Tests for selective sync with glob patterns."""

from loader import _merge_into_workspace


def test_include_filter(workspace, tmp_path):
    """Include filter only copies matching files."""
    source = tmp_path / "source"
    (source / "tools").mkdir(parents=True)
    (source / "tools" / "prod_deploy.py").write_text("def deploy(): pass")
    (source / "tools" / "dev_debug.py").write_text("def debug(): pass")

    _merge_into_workspace(workspace, source, include="prod_*")

    assert (workspace / "tools" / "prod_deploy.py").exists()
    assert not (workspace / "tools" / "dev_debug.py").exists()


def test_exclude_filter(workspace, tmp_path):
    """Exclude filter skips matching files."""
    source = tmp_path / "source"
    (source / "tools").mkdir(parents=True)
    (source / "tools" / "prod_deploy.py").write_text("def deploy(): pass")
    (source / "tools" / "experimental.py").write_text("def exp(): pass")

    _merge_into_workspace(workspace, source, exclude="experimental*")

    assert (workspace / "tools" / "prod_deploy.py").exists()
    assert not (workspace / "tools" / "experimental.py").exists()


def test_no_filters(workspace, tmp_path):
    """No filters copies all files."""
    source = tmp_path / "source"
    (source / "tools").mkdir(parents=True)
    (source / "tools" / "a.py").write_text("def a(): pass")
    (source / "tools" / "b.py").write_text("def b(): pass")

    _merge_into_workspace(workspace, source)

    assert (workspace / "tools" / "a.py").exists()
    assert (workspace / "tools" / "b.py").exists()
