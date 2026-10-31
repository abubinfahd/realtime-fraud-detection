"""
FastAPI application definition and lifecycle management.

Configures lifespan startup/shutdown hooks, Redis Pub/Sub streaming bridge,
CORS middleware, WebSocket routing, and real-time fraud prediction API endpoints.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fraud_detection.api.routes import alerts, health, metrics, ws
from fraud_detection.api.websocket_manager import manager
from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.ml.features import extract_features
from fraud_detection.ml.inference import InferenceEngine
from fraud_detection.schemas.transaction import TransactionEvent
from fraud_detection.storage.postgres_pool import PostgresPool
from fraud_detection.storage.redis_publisher import RedisPublisher
from fraud_detection.storage.transaction_repository import TransactionRepository

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


async def _redis_pubsub_bridge(app: FastAPI, redis_publisher: RedisPublisher) -> None:
    """
    Background subscriber task bridging Redis Pub/Sub events to active WebSockets.

    Consumes threat alerts from channel:fraud-alerts and fans out JSON frames
    to all registered WebSocket clients concurrently via ConnectionManager.
    """
    channel = settings.REDIS_ALERTS_CHANNEL
    logger.info("Starting Redis Pub/Sub WebSocket broadcast bridge", extra={"channel": channel})
    try:
        async for raw_message in redis_publisher.subscribe(channel):
            delivered = await manager.broadcast_json(raw_message)
            logger.debug(
                "Broadcasted Redis alert to WebSockets",
                extra={"clients_notified": delivered},
            )
    except asyncio.CancelledError:
        logger.info("Redis Pub/Sub WebSocket bridge cancelled during graceful shutdown")
    except Exception as exc:
        logger.warning(
            "Redis Pub/Sub bridge encountered an unexpected exception",
            extra={"error": str(exc)},
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Initializes the ML inference engine, PostgreSQL pool, Redis publisher,
    and runs the background Redis-to-WebSocket event streaming bridge.
    """
    logger.info(
        "Initializing Real-Time Fraud Detection Gateway", extra={"env": settings.ENVIRONMENT}
    )

    # 1. Initialize & cache ML Inference Engine
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

    # 2. Initialize PostgreSQL persistence layer
    pg_pool = PostgresPool(mock_mode=settings.ENVIRONMENT != "production")
    await pg_pool.initialize()
    app.state.postgres_pool = pg_pool
    app.state.transaction_repo = TransactionRepository(pg_pool)

    # 3. Initialize Redis Pub/Sub publisher
    redis_pub = RedisPublisher(mock_mode=settings.ENVIRONMENT != "production")
    await redis_pub.initialize()
    app.state.redis_publisher = redis_pub

    # 4. Launch background Redis-to-WebSocket bridge task
    bridge_task = asyncio.create_task(_redis_pubsub_bridge(app, redis_pub))
    app.state.bridge_task = bridge_task

    yield

    # Graceful Shutdown
    logger.info("Shutting down Real-Time Fraud Detection Gateway")
    bridge_task.cancel()
    try:
        await asyncio.wait_for(bridge_task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    await redis_pub.close()
    await pg_pool.close()


def create_app() -> FastAPI:
    """Factory creating and configuring the primary FastAPI application instance."""
    app = FastAPI(
        title="Real-Time Fraud Detection Streaming API",
        description="Event-driven streaming gateway for sub-millisecond fraud scoring, WebSocket alerts, and telemetry.",
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

    # Include modular sub-routers
    app.include_router(health.router)
    app.include_router(ws.router)
    app.include_router(metrics.router)
    app.include_router(alerts.router)

    # Mount live operations dashboard frontend
    dashboard_dir = Path(__file__).resolve().parent.parent.parent.parent / "dashboard"
    if dashboard_dir.is_dir():
        app.mount(
            "/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard"
        )

    @app.get("/mlops", response_class=HTMLResponse, tags=["MLOps"])
    async def mlops_dashboard() -> HTMLResponse:
        """Serve live MLOps interactive dashboard with experiment tracking and registry governance."""
        import sys
        import tempfile

        project_root = Path(__file__).resolve().parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from scripts.visualize_mlops import generate_html_dashboard, load_mlops_data

        artifacts_dir = project_root / "artifacts"
        mlops_html_path = artifacts_dir / "mlops_dashboard.html"
        if not mlops_html_path.exists():
            try:
                generate_html_dashboard(load_mlops_data(artifacts_dir), mlops_html_path)
            except OSError:
                mlops_html_path = Path(tempfile.gettempdir()) / "mlops_dashboard.html"
                generate_html_dashboard(load_mlops_data(artifacts_dir), mlops_html_path)
        return HTMLResponse(content=mlops_html_path.read_text(encoding="utf-8"))

    @app.get("/", tags=["General"])
    async def root() -> dict[str, Any]:
        """Root endpoint returning service identity and documentation links."""
        return {
            "name": "Real-Time Fraud Detection API",
            "version": "0.1.0",
            "status": "operational",
            "environment": settings.ENVIRONMENT,
            "dashboard": "/dashboard/",
            "mlops_dashboard": "/mlops",
            "docs": "/docs",
            "health": "/healthz",
            "websocket_stream": "/ws/live-stream",
            "metrics": "/api/v1/metrics",
            "recent_alerts": "/api/v1/alerts/recent",
        }

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


def main() -> None:
    """CLI launcher for the FastAPI streaming gateway server."""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Real-Time Fraud Detection Gateway")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Listening port (default: 8000)")
    parser.add_argument(
        "--reload", action="store_true", help="Enable hot reloading for development"
    )
    args = parser.parse_args()

    uvicorn.run(
        "fraud_detection.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
