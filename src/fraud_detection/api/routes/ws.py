"""
WebSocket Streaming Routes for Real-Time Threat Alerts.

Provides persistent bi-directional streaming endpoints (/ws/live-stream and /ws/alerts)
delivering sub-5ms fraud alerts and telemetry frames to connected browser clients.
"""

from datetime import UTC, datetime
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from fraud_detection.api.websocket_manager import manager
from fraud_detection.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["WebSocket Streaming"])


@router.websocket("/ws/live-stream")
@router.websocket("/ws/alerts")
async def websocket_live_stream_endpoint(websocket: WebSocket) -> None:
    """
    Persistent WebSocket endpoint for streaming real-time fraud alerts.

    Accepts browser/dashboard connections, registers them in the ConnectionManager,
    sends an initial handshake confirmation frame, and handles bidirectional heartbeats.
    """
    await manager.connect(websocket)

    # Dispatch welcome handshake frame
    welcome_frame = {
        "event_type": "CONNECTION_ESTABLISHED",
        "service": "fraud-detection-stream",
        "active_clients": manager.active_count,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    try:
        await websocket.send_text(json.dumps(welcome_frame))
    except Exception as exc:
        logger.warning("Failed to send welcome handshake frame", extra={"error": str(exc)})
        await manager.disconnect(websocket)
        return

    try:
        while True:
            # Await client frames (heartbeats, commands, or client pings)
            data = await websocket.receive_text()

            # Handle ping/pong heartbeats
            if data.strip().lower() == "ping":
                await websocket.send_text("pong")
                continue

            try:
                parsed = json.loads(data)
                action = parsed.get("action", "").lower()
                if action == "ping":
                    pong_frame = {
                        "event_type": "PONG",
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    await websocket.send_text(json.dumps(pong_frame))
                elif action == "get_stats":
                    stats = manager.get_metrics()
                    await websocket.send_text(json.dumps(stats))
            except json.JSONDecodeError:
                # Non-JSON plain text echo / keep-alive
                pass

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as exc:
        logger.info(
            "WebSocket connection closed due to client termination",
            extra={"error": str(exc)},
        )
        await manager.disconnect(websocket)
