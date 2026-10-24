"""
Operational Telemetry and Metrics Endpoints.

Provides /api/v1/metrics exposing WebSocket connection counts, broadcast throughput,
streaming latency metrics, and gateway uptime for operations dashboards.
"""

from datetime import UTC, datetime
import os
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from fraud_detection.api.websocket_manager import manager
from fraud_detection.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Telemetry & Metrics"])

_GATEWAY_START_TIME = time.monotonic()


class GatewayMetricsResponse(BaseModel):
    """Real-time gateway operational metrics schema."""

    service: str = "fraud-detection-gateway"
    active_websocket_clients: int = Field(..., description="Currently active WebSocket connections")
    total_broadcasts: int = Field(..., description="Total broadcast cycles dispatched")
    total_frames_delivered: int = Field(..., description="Total frames delivered to client sockets")
    uptime_seconds: float = Field(..., description="Process uptime in seconds")
    pid: int = Field(..., description="Operating system process ID")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")


@router.get("/metrics", response_model=GatewayMetricsResponse)
async def get_gateway_metrics() -> GatewayMetricsResponse:
    """
    Retrieve real-time streaming gateway metrics.

    Exposes connected client count, broadcast throughput, and service uptime.
    """
    ws_stats = manager.get_metrics()
    uptime = time.monotonic() - _GATEWAY_START_TIME

    return GatewayMetricsResponse(
        service="fraud-detection-gateway",
        active_websocket_clients=ws_stats["active_clients"],
        total_broadcasts=ws_stats["total_broadcasts"],
        total_frames_delivered=ws_stats["total_frames_delivered"],
        uptime_seconds=round(uptime, 2),
        pid=os.getpid(),
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/stats")
async def get_system_stats() -> dict[str, Any]:
    """Lightweight dictionary of active connection stats for rapid client polling."""
    return manager.get_metrics()
