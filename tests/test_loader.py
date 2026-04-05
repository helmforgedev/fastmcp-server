"""Tests for the multi-source loader."""

import pytest

from loader import ASSET_DIRS, _merge_into_workspace, _sync_inline, sync_sources


def test_sync_inline(workspace, tmp_path):
    """Inline source copies files correctly into workspace."""
    inline_dir = tmp_path / "inline"
    inline_dir.mkdir()
    tools_dir = inline_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "hello.py").write_text("def hello(): return 'hi'")

    _sync_inline(workspace, inline_dir)

    assert (workspace / "tools" / "hello.py").exists()
    assert (workspace / "tools" / "hello.py").read_text() == "def hello(): return 'hi'"


def test_sync_inline_overwrites(workspace, tmp_path):
    """Inline source overwrites existing files."""
    (workspace / "tools" / "hello.py").write_text("old content")

    inline_dir = tmp_path / "inline"
    inline_dir.mkdir()
    tools_dir = inline_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "hello.py").write_text("new content")

    _sync_inline(workspace, inline_dir)

    assert (workspace / "tools" / "hello.py").read_text() == "new content"


def test_merge_into_workspace(workspace, tmp_path):
    """Merge correctly copies from all asset directories."""
    source = tmp_path / "source"
    for d in ASSET_DIRS:
        (source / d).mkdir(parents=True)

    (source / "tools" / "a.py").write_text("tool a")
    (source / "knowledge" / "doc.md").write_text("# Doc")

    _merge_into_workspace(workspace, source)

    assert (workspace / "tools" / "a.py").read_text() == "tool a"
    assert (workspace / "knowledge" / "doc.md").read_text() == "# Doc"


def test_sync_sources_empty(workspace, monkeypatch):
    """No sources enabled — workspace stays empty but dirs exist."""
    monkeypatch.setenv("SOURCE_INLINE_DIR", "/nonexistent")
    sync_sources(str(workspace))

    for d in ASSET_DIRS:
        assert (workspace / d).is_dir()
        assert list((workspace / d).iterdir()) == []


def test_sync_sources_inline_only(workspace, tmp_path, monkeypatch):
    """Only inline source enabled."""
    inline_dir = tmp_path / "inline"
    (inline_dir / "tools").mkdir(parents=True)
    (inline_dir / "tools" / "test.py").write_text("def test(): pass")

    monkeypatch.setenv("SOURCE_INLINE_DIR", str(inline_dir))
    sync_sources(str(workspace))

    assert (workspace / "tools" / "test.py").exists()


@pytest.fixture
def s3_mock():
    """Mock S3 using moto."""
    from moto import mock_aws

    with mock_aws():
        import boto3

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")

        # Upload test files
        s3.put_object(
            Bucket="test-bucket", Key="tools/hello.py", Body=b"def hello(): return 'hi'"
        )
        s3.put_object(
            Bucket="test-bucket", Key="knowledge/doc.md", Body=b"# Doc from S3"
        )

        yield s3


def test_sync_s3(workspace, s3_mock, monkeypatch):
    """S3 source downloads files correctly."""
    monkeypatch.setenv("SOURCE_S3_ENABLED", "true")
    monkeypatch.setenv("SOURCE_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("SOURCE_S3_REGION", "us-east-1")
    monkeypatch.setenv("SOURCE_INLINE_DIR", "/nonexistent")

    sync_sources(str(workspace))

    assert (workspace / "tools" / "hello.py").exists()
    assert (workspace / "tools" / "hello.py").read_text() == "def hello(): return 'hi'"
    assert (workspace / "knowledge" / "doc.md").read_text() == "# Doc from S3"


def test_sync_s3_with_prefix(workspace, monkeypatch):
    """S3 source with prefix filters correctly."""
    from moto import mock_aws

    with mock_aws():
        import boto3

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        s3.put_object(
            Bucket="test-bucket",
            Key="prod/tools/hello.py",
            Body=b"def hello(): return 'prod'",
        )
        s3.put_object(
            Bucket="test-bucket",
            Key="dev/tools/hello.py",
            Body=b"def hello(): return 'dev'",
        )

        monkeypatch.setenv("SOURCE_S3_ENABLED", "true")
        monkeypatch.setenv("SOURCE_S3_BUCKET", "test-bucket")
        monkeypatch.setenv("SOURCE_S3_PREFIX", "prod")
        monkeypatch.setenv("SOURCE_S3_REGION", "us-east-1")
        monkeypatch.setenv("SOURCE_INLINE_DIR", "/nonexistent")

        sync_sources(str(workspace))

        assert (
            workspace / "tools" / "hello.py"
        ).read_text() == "def hello(): return 'prod'"


def test_merge_precedence(workspace, tmp_path, monkeypatch):
    """Inline overrides S3 (inline has higher precedence)."""
    from moto import mock_aws

    with mock_aws():
        import boto3

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        s3.put_object(
            Bucket="test-bucket", Key="tools/greet.py", Body=b"def greet(): return 's3'"
        )

        inline_dir = tmp_path / "inline"
        (inline_dir / "tools").mkdir(parents=True)
        (inline_dir / "tools" / "greet.py").write_text("def greet(): return 'inline'")

        monkeypatch.setenv("SOURCE_S3_ENABLED", "true")
        monkeypatch.setenv("SOURCE_S3_BUCKET", "test-bucket")
        monkeypatch.setenv("SOURCE_S3_REGION", "us-east-1")
        monkeypatch.setenv("SOURCE_INLINE_DIR", str(inline_dir))

        sync_sources(str(workspace))

        # Inline should win over S3
        assert (
            workspace / "tools" / "greet.py"
        ).read_text() == "def greet(): return 'inline'"
