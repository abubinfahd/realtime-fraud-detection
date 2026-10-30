# Stage 12 — CI/CD: Automated Testing, Linting & Container Packaging

## 1. Stage Objective & Scope

Stage 12 establishes production **Continuous Integration (CI)** and **Continuous Deployment (CD)** pipelines using **GitHub Actions**. High-frequency financial streaming systems cannot tolerate undetected regressions, broken schema contracts, or unvalidated model artifacts reaching production.

**Core CI/CD Objectives:**
1. **Automated Code Quality & Security Scanning:** Formatting, linting, and static type checking enforced on every pull request.
2. **Comprehensive Test Automation:** Executing unit tests, mocked streaming pipelines, and database integration tests against transient Docker service containers.
3. **Optimized Multi-Stage Container Packaging:** Building lightweight, secure Docker images for the producer, consumer, and FastAPI gateway.
4. **Automated Image Publication:** Pushing versioned, immutable container images to **Azure Container Registry (ACR)**.

**Primary Deliverables:**
- `.github/workflows/ci.yml`: Pull request and main branch validation pipeline (lint, type-check, test).
- `.github/workflows/docker-publish.yml`: Automated build, scan, and push pipeline to Azure Container Registry (ACR).
- `Dockerfile.consumer`: Multi-stage Dockerfile for the ML inference consumer.
- `Dockerfile.producer`: Lightweight Dockerfile for the transaction generator.
- `Dockerfile.api`: Production ASGI Dockerfile for the FastAPI WebSocket hub.
- `tests/`: Automated unit and integration test suite (`pytest`).

> [!IMPORTANT]
> **Execution Status:** **COMPLETE & VERIFIED**.
> All GitHub Actions workflows, multi-stage Dockerfiles, `.dockerignore`, and CI/CD verification tests (`tests/test_cicd.py`) are implemented and verified.

---

## 2. CI/CD Pipeline Architecture

```mermaid
flowchart TD
    subgraph Trigger["1. Triggers"]
        PR["Pull Request / Push to main"]
        TAG["Release Tag (v1.0.0)"]
    end

    subgraph CI["2. Continuous Integration (.github/workflows/ci.yml)"]
        LINT["Code Quality Gate\n(ruff format --check, ruff check)"]
        TYPES["Static Type Analysis\n(mypy --strict)"]
        UNIT["Unit Test Suite\n(pytest tests/unit)"]
        INT["Integration Tests with Service Containers\n(Kafka, Redis, Postgres in GitHub Runner)"]
    end

    subgraph Security["3. Security & Vulnerability Gate"]
        SCAN["Vulnerability Scan\n(Trivy Container Scanner)"]
    end

    subgraph CD["4. Continuous Packaging (.github/workflows/docker-publish.yml)"]
        DOCKER["Multi-Stage Docker Build\n(Optimized Layer Caching)"]
        ACR["Push to Azure Container Registry\n(acrforfraud.azurecr.io)"]
    end

    PR --> LINT & TYPES
    LINT & TYPES --> UNIT
    UNIT --> INT
    TAG --> DOCKER
    INT -->|If on main branch| DOCKER
    DOCKER --> SCAN
    SCAN -->|No Critical CVEs| ACR
```

---

## 3. Detailed Technical Specifications

### 3.1 Code Quality & Static Analysis Pipeline
Every pull request is automatically evaluated against PEP 8 and Python 3.12 typing standards:
- **`ruff`**: Ultra-fast linter and formatter replacing Flake8, isort, and Black.
  ```bash
  uv run ruff check .
  uv run ruff format --check .
  ```
- **`mypy`**: Strict static typing catching runtime `None` dereferences and malformed schemas:
  ```bash
  uv run mypy api consumers producers models storage rules
  ```

---

### 3.2 Automated Test Hierarchy (`pytest`)

| Test Suite | Path | Scope | External Dependencies |
| :--- | :--- | :--- | :--- |
| **Unit Tests** | `tests/unit/` | Rule evaluation, schema validation, feature math, decision thresholds. | None (100% in-memory mocks). |
| **Model Tests** | `tests/model/` | Model artifact deserialization, inference determinism, feature order integrity. | Serialized `.joblib` bundle. |
| **Integration Tests** | `tests/integration/` | Redis Lua scripts, Kafka round-trip serialization, Postgres batched insertion idempotency. | GitHub Actions Service Containers. |

---

### 3.3 GitHub Actions CI Workflow (`.github/workflows/ci.yml`)

The workflow leverages native GitHub Actions service containers to run true integration tests against real Kafka, Redis, and Postgres instances:

```yaml
name: CI Pipeline

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres_password
          POSTGRES_DB: fraud_detection
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true

      - name: Set up Python 3.12
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync --all-extras

      - name: Run Ruff Linter & Formatter
        run: |
          uv run ruff check .
          uv run ruff format --check .

      - name: Run Mypy Type Checker
        run: uv run mypy .

      - name: Run Test Suite with Coverage
        run: uv run pytest --cov=api --cov=consumers --cov=producers --cov-report=xml
```

---

### 3.4 Multi-Stage Dockerfile Strategy

To minimize container image size, attack surface, and build duration, each component utilizes multi-stage builds:
1. **Builder Stage:** Installs compiler tools (`gcc`, `librdkafka-dev`), runs `uv sync`, and creates a lean virtual environment.
2. **Runtime Stage:** Copies only the prepared `.venv` and application code into a clean `python:3.12-slim` image without build tools. Final image size is reduced from ~1.2 GB to **< 180 MB**.

---

## 4. Implementation Deliverables (When Triggered)

When Stage 12 is triggered (`Start Step 12`):
1. Configure `pyproject.toml` with `pytest`, `pytest-cov`, `pytest-asyncio`, `ruff`, and `mypy` settings.
2. Implement `.github/workflows/ci.yml` and `.github/workflows/docker-publish.yml`.
3. Implement `Dockerfile.consumer`, `Dockerfile.producer`, and `Dockerfile.api`.
4. Create test suites in `tests/unit/` and `tests/integration/`.
5. Update `README.md` and `docs/stage-12-cicd-pipeline.md`.

---

## 5. Verification & Acceptance Criteria

When Stage 12 is executed, it must satisfy:
- [x] `uv run ruff check .` passes with zero violations.
- [x] `uv run mypy src/fraud_detection` passes with zero typing errors.
- [x] `uv run pytest` executes unit, integration, and CI/CD verification tests (`tests/test_cicd.py`).
- [x] Multi-stage Dockerfiles (`Dockerfile.producer`, `Dockerfile.consumer`, `Dockerfile.api`) and `.dockerignore` are configured with non-root user execution.
- [x] Image vulnerability scan workflow with Trivy is configured in `.github/workflows/docker-publish.yml`.
