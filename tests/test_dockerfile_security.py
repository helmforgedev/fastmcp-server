from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_runs_as_non_root_and_uses_healthz_probe():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER 1000" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "http://localhost:8000/healthz" in dockerfile
    assert "http://localhost:8000/mcp" not in dockerfile


def test_runtime_dependencies_are_pinned_except_requests_floor():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    for line in requirements:
        dep = line.strip()
        if not dep or dep.startswith("#"):
            continue
        if dep.startswith("requests"):
            assert dep == "requests>=2.31"
            continue
        assert "==" in dep
