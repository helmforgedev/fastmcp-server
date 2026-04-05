"""Hot reload — filesystem watcher for inline source changes.

Watches /app/inline/ (or SOURCE_INLINE_DIR) for file changes and
re-registers tools/resources/prompts with the FastMCP instance.

Activated via MCP_HOT_RELOAD=true environment variable.
"""

import logging
import os
import threading

logger = logging.getLogger("fastmcp-server.hot-reload")

_watcher_thread = None
_stop_event = threading.Event()


def start_watcher(mcp, workspace: str, rebuild_fn) -> None:
    """Start filesystem watcher in a background thread."""
    global _watcher_thread

    if os.environ.get("MCP_HOT_RELOAD", "false").lower() != "true":
        return

    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        logger.warning(
            "MCP_HOT_RELOAD=true but watchdog not installed. Add 'watchdog' to EXTRA_PIP_PACKAGES."
        )
        return

    inline_dir = os.environ.get("SOURCE_INLINE_DIR", "/app/inline")
    if not os.path.isdir(inline_dir):
        logger.warning(
            "Hot reload enabled but inline dir %s does not exist", inline_dir
        )
        return

    class ReloadHandler(FileSystemEventHandler):
        def __init__(self):
            self._debounce_timer = None
            self._lock = threading.Lock()

        def _schedule_reload(self):
            with self._lock:
                if self._debounce_timer is not None:
                    self._debounce_timer.cancel()
                self._debounce_timer = threading.Timer(1.0, self._do_reload)
                self._debounce_timer.start()

        def _do_reload(self):
            logger.info("File change detected, reloading components...")
            try:
                rebuild_fn(mcp, workspace)
                logger.info("Hot reload complete")
            except Exception:
                logger.exception("Hot reload failed")

        def on_created(self, event):
            if not event.is_directory and event.src_path.endswith(".py"):
                self._schedule_reload()

        def on_modified(self, event):
            if not event.is_directory and event.src_path.endswith(".py"):
                self._schedule_reload()

        def on_deleted(self, event):
            if not event.is_directory and event.src_path.endswith(".py"):
                self._schedule_reload()

    observer = Observer()
    observer.schedule(ReloadHandler(), inline_dir, recursive=True)
    observer.daemon = True
    observer.start()

    logger.info("Hot reload enabled — watching %s", inline_dir)


def stop_watcher() -> None:
    """Stop the filesystem watcher."""
    _stop_event.set()
