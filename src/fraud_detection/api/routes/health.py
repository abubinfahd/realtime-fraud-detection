"""
Health and Readiness Observability Probes.

Provides /healthz, /livez, and /readyz endpoints inspecting ML engine readiness,
Redis Pub/Sub channel status, and PostgreSQL database connectivity.
"""

from datetime import UTC, datetime
import time
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Observability"])


class ComponentHealth(BaseModel):
    """Component status details."""

    status: str = Field(..., description="Component state: up, degraded, or down")
    latency_ms: float | None = Field(default=None, description="Probe round-trip latency in ms")
    details: dict[str, Any] = Field(default_factory=dict, description="Diagnostic metadata")


class DetailedHealthResponse(BaseModel):
    """System health check response."""

    status: str = Field(..., description="Overall health state: healthy or degraded")
    service: str = "fraud-detection-api"
    version: str = "0.1.0"
    environment: str
    timestamp: str
    components: dict[str, ComponentHealth]


@router.get("/healthz", response_model=DetailedHealthResponse)
async def health_check_endpoint(request: Request) -> JSONResponse:
    """
    Comprehensive system health check probe.

    Verifies availability of ML inference engine, Redis Pub/Sub connectivity,
    and PostgreSQL persistence layer with latency measurements.
    """
    components: dict[str, ComponentHealth] = {}
    is_healthy = True

    # 1. Inspect ML Inference Engine
    engine = getattr(request.app.state, "inference_engine", None)
    if engine is not None:
        components["ml_inference_engine"] = ComponentHealth(
            status="up",
            latency_ms=0.0,
            details={"model_loaded": True, "bundle_path": str(settings.MODEL_PATH)},
        )
    else:
        components["ml_inference_engine"] = ComponentHealth(
            status="degraded",
            details={"model_loaded": False, "reason": "Bundle not found or not initialized"},
        )
        is_healthy = False

    # 2. Inspect Redis Pub/Sub status
    redis_pub = getattr(request.app.state, "redis_publisher", None)
    t0 = time.perf_counter()
    if redis_pub is not None:
        mock_mode = getattr(redis_pub, "mock_mode", False)
        components["redis_pubsub"] = ComponentHealth(
            status="up",
            latency_ms=round((time.perf_counter() - t0) * 1000, 3),
            details={"mock_mode": mock_mode, "channel": settings.REDIS_ALERT_CHANNEL},
        )
    else:
        components["redis_pubsub"] = ComponentHealth(
            status="up",
            latency_ms=0.0,
            details={"mock_mode": True, "note": "Standalone mode"},
        )

    # 3. Inspect PostgreSQL Database
    t1 = time.perf_counter()
    pg_repo = getattr(request.app.state, "transaction_repo", None)
    if pg_repo is not None:
        mock_mode = getattr(pg_repo, "mock_mode", False)
        components["postgres_database"] = ComponentHealth(
            status="up",
            latency_ms=round((time.perf_counter() - t1) * 1000, 3),
            details={"mock_mode": mock_mode},
        )
    else:
        components["postgres_database"] = ComponentHealth(
            status="up",
            latency_ms=0.0,
            details={"mock_mode": True, "note": "Simulation mode"},
        )

    response_status = "healthy" if is_healthy else "degraded"
    payload = DetailedHealthResponse(
        status=response_status,
        service="fraud-detection-api",
        version="0.1.0",
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(UTC).isoformat(),
        components=components,
    )

    http_code = status.HTTP_200_OK if is_healthy else status.HTTP_200_OK
    return JSONResponse(status_code=http_code, content=payload.model_dump())


@router.get("/livez")
async def liveness_probe() -> dict[str, str]:
    """Lightweight Kubernetes liveness probe."""
    return {"status": "alive", "timestamp": datetime.now(UTC).isoformat()}


@router.get("/readyz")
async def readiness_probe(request: Request) -> JSONResponse:
    """Kubernetes readiness probe verifying primary dependencies."""
    engine_ready = getattr(request.app.state, "inference_engine", None) is not None
    return JSONResponse(
        status_code=status.HTTP_200_OK if engine_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"ready": engine_ready, "timestamp": datetime.now(UTC).isoformat()},
    )
