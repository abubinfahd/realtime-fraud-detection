"""
FastAPI application definition and lifecycle management.

Configures lifespan startup/shutdown hooks, CORS middleware,
health checks, and real-time fraud prediction API endpoints.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.ml.features import extract_features
from fraud_detection.ml.inference import InferenceEngine
from fraud_detection.schemas.transaction import TransactionEvent

logger = get_logger(__name__)


class PredictionResponse(BaseModel):
    """Real-time fraud scoring response."""

    transaction_id: str
    status: str = Field(..., description="Decision verdict: APPROVED, FLAGGED, or REJECTED")
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Blended risk score [0, 1]")
    fraud_probability: float = Field(
        ..., ge=0.0, le=1.0, description="Supervised LightGBM probability"
    )
    anomaly_score: float = Field(
        ..., ge=0.0, le=1.0, description="Unsupervised Isolation Forest score"
    )
    latency_ms: float = Field(
        ..., ge=0.0, description="End-to-end inference execution latency in ms"
    )


class HealthResponse(BaseModel):
    """System health and readiness response."""

    status: str
    service: str
    version: str
    environment: str
    model_loaded: bool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context: initialize and cache ML inference engine."""
    logger.info("Initializing Real-Time Fraud Detection API", extra={"env": settings.ENVIRONMENT})

    if settings.MODEL_PATH.exists():
        try:
            app.state.inference_engine = InferenceEngine(model_path=settings.MODEL_PATH)
            logger.info("ML Inference Engine successfully cached in app state")
        except (FileNotFoundError, ValueError, KeyError, RuntimeError, OSError) as exc:
            logger.error("Failed to load model bundle into memory", extra={"error": str(exc)})
            app.state.inference_engine = None
    else:
        logger.warning(
            "Model bundle not found. Run 'uv run fraud-train' to train model.",
            extra={"path": str(settings.MODEL_PATH)},
        )
        app.state.inference_engine = None

    yield

    logger.info("Shutting down Real-Time Fraud Detection API")


def create_app() -> FastAPI:
    """Factory creating and configuring the primary FastAPI application instance."""
    app = FastAPI(
        title="Real-Time Fraud Detection Streaming API",
        description="Event-driven streaming API for sub-millisecond fraud scoring, WebSocket alerts, and telemetry.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Allow local development and dashboard origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["General"])
    async def root() -> dict[str, Any]:
        """Root endpoint returning service identity and documentation links."""
        return {
            "name": "Real-Time Fraud Detection API",
            "version": "0.1.0",
            "status": "operational",
            "environment": settings.ENVIRONMENT,
            "docs": "/docs",
            "health": "/healthz",
        }

    @app.get("/healthz", response_model=HealthResponse, tags=["Observability"])
    async def health_check() -> HealthResponse:
        """Readiness and health status probe."""
        model_ready = getattr(app.state, "inference_engine", None) is not None
        return HealthResponse(
            status="healthy" if model_ready else "degraded",
            service="fraud-detection-api",
            version="0.1.0",
            environment=settings.ENVIRONMENT,
            model_loaded=model_ready,
        )

    @app.post(
        "/api/v1/predict",
        response_model=PredictionResponse,
        status_code=status.HTTP_200_OK,
        tags=["Inference"],
    )
    async def predict_transaction(event: TransactionEvent) -> PredictionResponse:
        """
        Evaluate an inbound financial transaction event for fraud risk.

        Extracts canonical 10-dimensional feature vector and scores via hybrid
        supervised (LightGBM) + unsupervised (Isolation Forest) engine.
        """
        engine: InferenceEngine | None = getattr(app.state, "inference_engine", None)
        if engine is None:
            # Attempt on-demand load if model was trained recently
            if settings.MODEL_PATH.exists():
                engine = InferenceEngine(model_path=settings.MODEL_PATH)
                app.state.inference_engine = engine
            else:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Model bundle not loaded. Run 'uv run fraud-train' first.",
                )

        # Extract features conforming to canonical 10-feature contract
        raw_dict = event.model_dump()
        feature_vector = extract_features(transaction=raw_dict)

        # Execute sub-millisecond CPU scoring
        result = engine.predict(feature_vector)

        return PredictionResponse(
            transaction_id=event.transaction_id,
            status=result["status"],
            risk_score=result["risk_score"],
            fraud_probability=result["fraud_probability"],
            anomaly_score=result["anomaly_score"],
            latency_ms=result["latency_ms"],
        )

    return app
