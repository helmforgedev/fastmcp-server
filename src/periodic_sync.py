"""Periodic source synchronization for S3 and Git.

Polls remote sources at configurable intervals and re-syncs
changed files into the workspace.

Environment variables:
  SOURCE_S3_SYNC_INTERVAL  — seconds between S3 syncs (0 = disabled)
  SOURCE_GIT_SYNC_INTERVAL — seconds between Git syncs (0 = disabled)
"""

import hashlib
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("fastmcp-server.periodic-sync")

_stop_event = threading.Event()
_threads: list[threading.Thread] = []


def _file_checksum(path: Path) -> str:
    """Compute MD5 checksum of a file."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _workspace_checksums(workspace: str) -> dict[str, str]:
    """Build a checksum map of all files in workspace."""
    ws = Path(workspace)
    checksums = {}
    for f in ws.rglob("*"):
        if f.is_file() and not f.name.startswith("."):
            rel = str(f.relative_to(ws))
            checksums[rel] = _file_checksum(f)
    return checksums


def start_periodic_sync(workspace: str, sync_fn, rebuild_fn, mcp) -> None:
    """Start periodic sync threads for S3 and Git."""
    s3_interval = int(os.environ.get("SOURCE_S3_SYNC_INTERVAL", "0"))
    git_interval = int(os.environ.get("SOURCE_GIT_SYNC_INTERVAL", "0"))

    if (
        s3_interval > 0
        and os.environ.get("SOURCE_S3_ENABLED", "false").lower() == "true"
    ):
        t = threading.Thread(
            target=_sync_loop,
            args=(workspace, "s3", s3_interval, sync_fn, rebuild_fn, mcp),
            daemon=True,
        )
        t.start()
        _threads.append(t)
        logger.info("Periodic S3 sync enabled (every %ds)", s3_interval)

    if (
        git_interval > 0
        and os.environ.get("SOURCE_GIT_ENABLED", "false").lower() == "true"
    ):
        t = threading.Thread(
            target=_sync_loop,
            args=(workspace, "git", git_interval, sync_fn, rebuild_fn, mcp),
            daemon=True,
        )
        t.start()
        _threads.append(t)
        logger.info("Periodic Git sync enabled (every %ds)", git_interval)


def _sync_loop(
    workspace: str, source: str, interval: int, sync_fn, rebuild_fn, mcp
) -> None:
    """Background sync loop for a single source."""
    from metrics import record_source_sync

    while not _stop_event.wait(interval):
        before = _workspace_checksums(workspace)
        try:
            sync_fn(workspace)
            record_source_sync(source, True)
        except Exception:
            logger.exception("Periodic %s sync failed", source)
            record_source_sync(source, False)
            continue

        after = _workspace_checksums(workspace)
        if before != after:
            added = set(after.keys()) - set(before.keys())
            changed = {k for k in before if k in after and before[k] != after[k]}
            removed = set(before.keys()) - set(after.keys())
            logger.info(
                "%s sync: %d added, %d changed, %d removed",
                source.upper(),
                len(added),
                len(changed),
                len(removed),
            )
            try:
                rebuild_fn(mcp, workspace)
            except Exception:
                logger.exception("Failed to rebuild after %s sync", source)
        else:
            logger.debug("%s sync: no changes", source.upper())


def stop_periodic_sync() -> None:
    """Stop all periodic sync threads."""
    _stop_event.set()
