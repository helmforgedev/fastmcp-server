"""Multi-source loader for FastMCP server assets.

Supports three sources with merge precedence:
  1. Inline (ConfigMap, mounted at /app/inline/) - highest precedence
  2. S3-compatible storage (AWS S3, MinIO, Cloudflare R2)
  3. Git repository - lowest precedence

Files are synced into the workspace directory organized by type:
  workspace/tools/*.py
  workspace/resources/*.py
  workspace/prompts/*.py
  workspace/knowledge/*
"""

import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("fastmcp-server.loader")

ASSET_DIRS = ["tools", "resources", "prompts", "knowledge"]


def sync_sources(workspace: str) -> None:
    """Sync all configured sources into the workspace directory."""
    ws = Path(workspace)

    # Ensure workspace structure exists
    for d in ASSET_DIRS:
        (ws / d).mkdir(parents=True, exist_ok=True)

    # Source 3 (lowest precedence): Git
    if os.environ.get("SOURCE_GIT_ENABLED", "false").lower() == "true":
        _sync_git(ws)

    # Source 2: S3
    if os.environ.get("SOURCE_S3_ENABLED", "false").lower() == "true":
        _sync_s3(ws)

    # Source 1 (highest precedence): Inline (ConfigMap mounts)
    inline_dir = Path(os.environ.get("SOURCE_INLINE_DIR", "/app/inline"))
    if inline_dir.exists():
        _sync_inline(ws, inline_dir)

    # Log summary
    for d in ASSET_DIRS:
        files = list((ws / d).iterdir())
        if files:
            logger.info("Loaded %d file(s) from %s/", len(files), d)


def _sync_git(workspace: Path) -> None:
    """Clone or pull a Git repository into the workspace."""
    import git

    repo_url = os.environ.get("SOURCE_GIT_REPOSITORY", "")
    branch = os.environ.get("SOURCE_GIT_BRANCH", "main")
    subpath = os.environ.get("SOURCE_GIT_PATH", "")
    token = os.environ.get("SOURCE_GIT_TOKEN", "")

    if not repo_url:
        logger.warning("Git source enabled but SOURCE_GIT_REPOSITORY not set")
        return

    # Inject token into HTTPS URL if provided
    if token and repo_url.startswith("https://"):
        repo_url = repo_url.replace("https://", f"https://x-access-token:{token}@")

    clone_dir = workspace / ".git-source"
    if clone_dir.exists():
        shutil.rmtree(clone_dir)

    logger.info("Cloning %s (branch: %s)...", os.environ.get("SOURCE_GIT_REPOSITORY"), branch)
    repo = git.Repo.clone_from(repo_url, str(clone_dir), branch=branch, depth=1)
    logger.info("Git clone complete: %s", repo.head.commit.hexsha[:8])

    source_root = clone_dir / subpath if subpath else clone_dir
    _merge_into_workspace(workspace, source_root)


def _sync_s3(workspace: Path) -> None:
    """Download assets from an S3-compatible bucket."""
    import boto3
    from botocore.config import Config

    endpoint = os.environ.get("SOURCE_S3_ENDPOINT", "")
    bucket = os.environ.get("SOURCE_S3_BUCKET", "")
    region = os.environ.get("SOURCE_S3_REGION", "us-east-1")
    prefix = os.environ.get("SOURCE_S3_PREFIX", "").strip("/")
    access_key = os.environ.get("SOURCE_S3_ACCESS_KEY", "")
    secret_key = os.environ.get("SOURCE_S3_SECRET_KEY", "")

    if not bucket:
        logger.warning("S3 source enabled but SOURCE_S3_BUCKET not set")
        return

    logger.info("Syncing from s3://%s/%s...", bucket, prefix)

    client_kwargs = {"region_name": region, "config": Config(signature_version="s3v4")}
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint
    if access_key and secret_key:
        client_kwargs["aws_access_key_id"] = access_key
        client_kwargs["aws_secret_access_key"] = secret_key

    s3 = boto3.client("s3", **client_kwargs)

    paginator = s3.get_paginator("list_objects_v2")
    page_kwargs = {"Bucket": bucket}
    if prefix:
        page_kwargs["Prefix"] = prefix + "/"

    s3_dir = workspace / ".s3-source"
    if s3_dir.exists():
        shutil.rmtree(s3_dir)
    s3_dir.mkdir(parents=True)

    count = 0
    for page in paginator.paginate(**page_kwargs):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # Strip prefix to get relative path
            rel_path = key[len(prefix):].lstrip("/") if prefix else key
            if not rel_path or rel_path.endswith("/"):
                continue

            local_path = s3_dir / rel_path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(local_path))
            count += 1

    logger.info("Downloaded %d file(s) from S3", count)
    _merge_into_workspace(workspace, s3_dir)


def _sync_inline(workspace: Path, inline_dir: Path) -> None:
    """Copy inline (ConfigMap-mounted) files into workspace."""
    logger.info("Loading inline sources from %s...", inline_dir)
    _merge_into_workspace(workspace, inline_dir)


def _merge_into_workspace(workspace: Path, source: Path) -> None:
    """Merge source directory into workspace, overwriting existing files.

    Expected source structure:
      source/tools/*.py
      source/resources/*.py
      source/prompts/*.py
      source/knowledge/*
    """
    for asset_dir in ASSET_DIRS:
        src = source / asset_dir
        if not src.is_dir():
            continue
        dst = workspace / asset_dir
        for item in src.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src)
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                logger.debug("Merged: %s -> %s", rel, asset_dir)
