"""Tests for package_discovery module."""

from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from package_discovery import discover_tool_packages, install_discovered_tools


@pytest.fixture
def tool_dir(tmp_path):
    """Create a temp directory with tool .py files."""
    d = tmp_path / "tools"
    d.mkdir()
    (d / "__init__.py").write_text("")
    (d / "get_pods.py").write_text("def get_pods(): pass")
    (d / "get_logs.py").write_text("def get_logs(): pass")
    return d


@pytest.fixture
def fake_module(tool_dir):
    """Create a fake module with TOOLS_DIR attribute."""
    mod = ModuleType("tools.kubernetes")
    mod.TOOLS_DIR = tool_dir
    return mod


def _make_entry_point(name, module):
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = module
    return ep


def _noop_reload(module):
    """No-op reload to prevent importlib.reload from destroying mocks."""
    return module


class TestDiscoverToolPackages:
    @patch("importlib.reload", _noop_reload)
    @patch("importlib.metadata.entry_points")
    def test_discovers_packages(self, mock_ep, fake_module):
        mock_ep.return_value = [_make_entry_point("kubernetes", fake_module)]

        result = discover_tool_packages()

        assert len(result) == 1
        assert result[0]["name"] == "kubernetes"
        assert result[0]["file_count"] == 2

    @patch("importlib.reload", _noop_reload)
    @patch("importlib.metadata.entry_points")
    def test_excludes_init_files(self, mock_ep, fake_module):
        mock_ep.return_value = [_make_entry_point("kubernetes", fake_module)]

        result = discover_tool_packages()
        filenames = [f.name for f in result[0]["files"]]

        assert "__init__.py" not in filenames

    @patch("importlib.reload", _noop_reload)
    @patch("importlib.metadata.entry_points")
    def test_skips_missing_tools_dir(self, mock_ep):
        mod = ModuleType("bad")
        mod.TOOLS_DIR = None
        mock_ep.return_value = [_make_entry_point("bad", mod)]

        result = discover_tool_packages()

        assert len(result) == 0

    @patch("importlib.reload", _noop_reload)
    @patch("importlib.metadata.entry_points")
    def test_skips_empty_tools_dir(self, mock_ep, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        (d / "__init__.py").write_text("")
        mod = ModuleType("empty")
        mod.TOOLS_DIR = d
        mock_ep.return_value = [_make_entry_point("empty", mod)]

        result = discover_tool_packages()

        assert len(result) == 0

    @patch("importlib.reload", _noop_reload)
    @patch("importlib.metadata.entry_points")
    def test_handles_load_error(self, mock_ep):
        ep = MagicMock()
        ep.name = "broken"
        ep.load.side_effect = ImportError("no module")
        mock_ep.return_value = [ep]

        result = discover_tool_packages()

        assert len(result) == 0

    def test_returns_empty_when_no_entry_points(self):
        with patch("importlib.reload", _noop_reload), patch(
            "importlib.metadata.entry_points", side_effect=Exception("no group")
        ):
            result = discover_tool_packages()
            assert result == []


class TestInstallDiscoveredTools:
    def test_copies_files_to_workspace(self, tmp_path, tool_dir):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        packages = [
            {
                "name": "kubernetes",
                "tools_dir": tool_dir,
                "files": [tool_dir / "get_pods.py", tool_dir / "get_logs.py"],
                "file_count": 2,
            }
        ]

        count = install_discovered_tools(str(workspace), packages)

        assert count == 2
        assert (workspace / "tools" / "kubernetes_get_pods.py").exists()
        assert (workspace / "tools" / "kubernetes_get_logs.py").exists()

    def test_returns_zero_for_empty_packages(self, tmp_path):
        assert install_discovered_tools(str(tmp_path), []) == 0

    def test_creates_tools_dir_if_missing(self, tmp_path, tool_dir):
        workspace = tmp_path / "new_workspace"
        workspace.mkdir()
        packages = [
            {
                "name": "http",
                "tools_dir": tool_dir,
                "files": [tool_dir / "get_pods.py"],
                "file_count": 1,
            }
        ]

        install_discovered_tools(str(workspace), packages)

        assert (workspace / "tools").is_dir()

    def test_prefixes_avoid_collisions(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        d1 = tmp_path / "pkg1"
        d1.mkdir()
        (d1 / "fetch.py").write_text("# pkg1")

        d2 = tmp_path / "pkg2"
        d2.mkdir()
        (d2 / "fetch.py").write_text("# pkg2")

        packages = [
            {
                "name": "http",
                "tools_dir": d1,
                "files": [d1 / "fetch.py"],
                "file_count": 1,
            },
            {
                "name": "github",
                "tools_dir": d2,
                "files": [d2 / "fetch.py"],
                "file_count": 1,
            },
        ]

        count = install_discovered_tools(str(workspace), packages)

        assert count == 2
        assert (workspace / "tools" / "http_fetch.py").read_text() == "# pkg1"
        assert (workspace / "tools" / "github_fetch.py").read_text() == "# pkg2"
