"""Tests for package_discovery module."""

import json
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


def _subprocess_result(packages, returncode=0, stderr=""):
    """Create a mock subprocess result with JSON output."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = json.dumps(packages)
    result.stderr = stderr
    return result


class TestDiscoverToolPackages:
    @patch("package_discovery.subprocess.run")
    def test_discovers_packages(self, mock_run, tool_dir):
        mock_run.return_value = _subprocess_result(
            [{"name": "kubernetes", "tools_dir": str(tool_dir)}]
        )

        result = discover_tool_packages()

        assert len(result) == 1
        assert result[0]["name"] == "kubernetes"
        assert result[0]["file_count"] == 2

    @patch("package_discovery.subprocess.run")
    def test_excludes_init_files(self, mock_run, tool_dir):
        mock_run.return_value = _subprocess_result(
            [{"name": "kubernetes", "tools_dir": str(tool_dir)}]
        )

        result = discover_tool_packages()
        filenames = [f.name for f in result[0]["files"]]

        assert "__init__.py" not in filenames

    @patch("package_discovery.subprocess.run")
    def test_skips_missing_tools_dir(self, mock_run, tmp_path):
        mock_run.return_value = _subprocess_result(
            [{"name": "bad", "tools_dir": str(tmp_path / "nonexistent")}]
        )

        result = discover_tool_packages()

        assert len(result) == 0

    @patch("package_discovery.subprocess.run")
    def test_skips_empty_tools_dir(self, mock_run, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        (d / "__init__.py").write_text("")
        mock_run.return_value = _subprocess_result(
            [{"name": "empty", "tools_dir": str(d)}]
        )

        result = discover_tool_packages()

        assert len(result) == 0

    @patch("package_discovery.subprocess.run")
    def test_handles_subprocess_failure(self, mock_run):
        mock_run.return_value = _subprocess_result([], returncode=1, stderr="error")

        result = discover_tool_packages()

        assert len(result) == 0

    @patch("package_discovery.subprocess.run")
    def test_handles_subprocess_exception(self, mock_run):
        mock_run.side_effect = Exception("timeout")

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
