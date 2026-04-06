"""Auto-discover tool packages installed via pip.

Scans the `fastmcp_tools` entry point group for installed packages.
Each package exposes a module with a `TOOLS_DIR` attribute pointing
to the directory containing tool Python files.

Usage:
  EXTRA_PIP_PACKAGES=fastmcp-tools-kubernetes,fastmcp-tools-github

The entrypoint calls discover_tool_packages() after pip install,
which copies discovered tool files into the workspace tools directory.
"""

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("fastmcp-server.package_discovery")

# Subprocess script that discovers entry points in a fresh Python process.
# This is necessary because Python 3.13's importlib.metadata caches the
# package index at first import. Packages installed via subprocess pip
# after process start are invisible to entry_points() even after
# invalidate_caches() and reload(). A fresh process sees them correctly.
_DISCOVER_SCRIPT = """\
import json
from importlib.metadata import entry_points

result = []
for ep in entry_points(group="fastmcp_tools"):
    try:
        module = ep.load()
        tools_dir = getattr(module, "TOOLS_DIR", None)
        if tools_dir is None:
            continue
        result.append({"name": ep.name, "tools_dir": str(tools_dir)})
    except Exception:
        pass
print(json.dumps(result))
"""


def discover_tool_packages() -> list[dict]:
    """Discover installed fastmcp-tools-* packages via entry points.

    Runs discovery in a subprocess to avoid importlib.metadata caching
    issues with runtime-installed packages.

    Returns a list of dicts with keys: name, tools_dir, file_count, files.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", _DISCOVER_SCRIPT],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("Discovery subprocess failed: %s", result.stderr.strip())
            return []

        raw = json.loads(result.stdout.strip())
    except Exception:
        logger.warning("Failed to scan fastmcp_tools entry points", exc_info=True)
        return []

    discovered = []
    for pkg in raw:
        tools_dir = Path(pkg["tools_dir"])
        if not tools_dir.is_dir():
            logger.warning("Package '%s' has no valid TOOLS_DIR, skipping", pkg["name"])
            continue

        py_files = [f for f in tools_dir.glob("*.py") if f.name != "__init__.py"]
        if not py_files:
            logger.warning(
                "Package '%s' has no tool files in %s", pkg["name"], tools_dir
            )
            continue

        discovered.append(
            {
                "name": pkg["name"],
                "tools_dir": tools_dir,
                "files": py_files,
                "file_count": len(py_files),
            }
        )
        logger.info(
            "Discovered tool package '%s': %d tool(s) at %s",
            pkg["name"],
            len(py_files),
            tools_dir,
        )

    logger.info("Entry points scan: found %d fastmcp_tools package(s)", len(discovered))
    return discovered


def install_discovered_tools(workspace: str, packages: list[dict]) -> int:
    """Copy discovered tool files into the workspace tools directory.

    Returns the number of tool files installed.
    """
    if not packages:
        return 0

    tools_dir = Path(workspace) / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for pkg in packages:
        for tool_file in pkg["files"]:
            # Prefix with package name to avoid collisions
            dest_name = f"{pkg['name']}_{tool_file.name}"
            dest = tools_dir / dest_name
            try:
                shutil.copy2(tool_file, dest)
                logger.debug("Installed tool: %s -> %s", tool_file.name, dest_name)
                count += 1
            except Exception:
                logger.exception("Failed to copy %s", tool_file)

    logger.info("Installed %d tool file(s) from %d package(s)", count, len(packages))
    return count
