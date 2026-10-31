"""Automated verification tests for Stage 12 CI/CD & Container Packaging."""

from pathlib import Path
import tomllib

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestDockerPackaging:
    """Validate multi-stage Dockerfiles and .dockerignore security/size best practices."""

    @pytest.mark.parametrize(
        ("dockerfile_name", "expected_entrypoint"),
        [
            ("Dockerfile.producer", "scripts/run_producer.py"),
            ("Dockerfile.consumer", "scripts/run_consumer.py"),
            ("Dockerfile.api", "scripts/run_gateway.py"),
        ],
    )
    def test_multistage_dockerfile_structure(
        self, dockerfile_name: str, expected_entrypoint: str
    ) -> None:
        """Verify each Dockerfile uses multi-stage builds, non-root user, and valid entrypoint."""
        dockerfile_path = PROJECT_ROOT / dockerfile_name
        assert dockerfile_path.exists(), f"{dockerfile_name} is missing"

        content = dockerfile_path.read_text(encoding="utf-8")

        # 1. Multi-stage build verification
        assert "FROM python:3.12-slim AS builder" in content
        assert "FROM python:3.12-slim AS runtime" in content
        assert "uv sync --no-dev" in content

        # 2. Security: non-root execution
        assert "useradd" in content
        assert "10001" in content
        assert "USER appuser" in content

        # 3. Runtime environment & entrypoint
        assert "PYTHONUNBUFFERED=1" in content
        assert expected_entrypoint in content

    def test_api_dockerfile_exposes_port_and_healthcheck(self) -> None:
        """Verify Dockerfile.api exposes port 8000 and defines a container HEALTHCHECK."""
        content = (PROJECT_ROOT / "Dockerfile.api").read_text(encoding="utf-8")
        assert "EXPOSE 8000" in content
        assert "HEALTHCHECK" in content
        assert "/livez" in content

    def test_dockerignore_excludes_sensitive_and_heavy_paths(self) -> None:
        """Verify .dockerignore prevents virtualenvs, git history, and secrets from bloating images."""
        dockerignore_path = PROJECT_ROOT / ".dockerignore"
        assert dockerignore_path.exists(), ".dockerignore is missing"

        content = dockerignore_path.read_text(encoding="utf-8")
        for excluded_item in [".git", ".venv", "__pycache__", "mlruns", ".env", "tests", "docs"]:
            assert excluded_item in content, f"{excluded_item} must be listed in .dockerignore"


class TestGitHubActionsWorkflows:
    """Validate GitHub Actions CI and Docker Publish workflow definitions."""

    def test_ci_workflow_configuration(self) -> None:
        """Verify .github/workflows/ci.yml defines service containers and quality gates."""
        ci_path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
        assert ci_path.exists(), ".github/workflows/ci.yml is missing"

        content = ci_path.read_text(encoding="utf-8")
        assert "redis:7-alpine" in content
        assert "postgres:16-alpine" in content
        assert "uv run ruff check ." in content
        assert "uv run mypy src/fraud_detection" in content
        assert "uv run pytest --cov=src/fraud_detection" in content

    def test_docker_publish_workflow_configuration(self) -> None:
        """Verify .github/workflows/docker-publish.yml builds all 3 services and runs Trivy scan."""
        publish_path = PROJECT_ROOT / ".github" / "workflows" / "docker-publish.yml"
        assert publish_path.exists(), ".github/workflows/docker-publish.yml is missing"

        content = publish_path.read_text(encoding="utf-8")
        assert "Dockerfile.producer" in content
        assert "Dockerfile.consumer" in content
        assert "Dockerfile.api" in content
        assert "aquasecurity/trivy-action" in content
        assert "docker/build-push-action" in content


class TestProjectToolingConfig:
    """Verify pyproject.toml defines ruff, mypy, pytest, and coverage sections."""

    def test_pyproject_toml_ci_sections(self) -> None:
        """Verify pyproject.toml parses cleanly and contains required CI tool configurations."""
        pyproject_path = PROJECT_ROOT / "pyproject.toml"
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

        tool_cfg = data.get("tool", {})
        assert "ruff" in tool_cfg
        assert "mypy" in tool_cfg
        assert "pytest" in tool_cfg
        assert "coverage" in tool_cfg
        assert tool_cfg["mypy"]["python_version"] == "3.12"
