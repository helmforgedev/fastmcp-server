"""Auto-discover tool packages installed via pip.

Scans the `fastmcp_tools` entry point group for installed packages.
Each package exposes a module with a `TOOLS_DIR` attribute pointing
to the directory containing tool Python files.

Usage:
  EXTRA_PIP_PACKAGES=fastmcp-tools-kubernetes,fastmcp-tools-github

The entrypoint calls discover_tool_packages() after pip install,
which copies discovered tool files into the workspace tools directory.
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger("fastmcp-server.package_discovery")


def discover_tool_packages() -> list[dict]:
    """Discover installed fastmcp-tools-* packages via entry points.

    Returns a list of dicts with keys: name, tools_dir, file_count.
    """
    discovered = []

    try:
        import importlib
        import importlib.metadata

        # Force fresh metadata scan after runtime pip installs.
        # Without this, entry_points() returns stale (empty) results when
        # packages were installed via subprocess pip after process start.
        importlib.invalidate_caches()
        importlib.reload(importlib.metadata)
        from importlib.metadata import entry_points

        eps = entry_points(group="fastmcp_tools")
        logger.info("Entry points scan: found %d fastmcp_tools package(s)", len(eps))
    except Exception:
        logger.warning("Failed to scan fastmcp_tools entry points", exc_info=True)
        return discovered

    for ep in eps:
        try:
            module = ep.load()
            tools_dir = getattr(module, "TOOLS_DIR", None)
            if tools_dir is None or not Path(tools_dir).is_dir():
                logger.warning("Package '%s' has no valid TOOLS_DIR, skipping", ep.name)
                continue

            tools_dir = Path(tools_dir)
            py_files = list(tools_dir.glob("*.py"))
            # Exclude __init__.py
            py_files = [f for f in py_files if f.name != "__init__.py"]

            if not py_files:
                logger.warning(
                    "Package '%s' has no tool files in %s", ep.name, tools_dir
                )
                continue

            discovered.append(
                {
                    "name": ep.name,
                    "tools_dir": tools_dir,
                    "files": py_files,
                    "file_count": len(py_files),
                }
            )
            logger.info(
                "Discovered tool package '%s': %d tool(s) at %s",
                ep.name,
                len(py_files),
                tools_dir,
            )

        except Exception:
            logger.exception("Failed to load tool package '%s'", ep.name)

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
