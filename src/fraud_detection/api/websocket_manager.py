"""
WebSocket Connection Manager for Real-Time Threat Broadcasting.

Maintains active browser connections, manages client lifecycles, and executes
concurrent, non-blocking fan-out of fraud alert payloads via asyncio.gather.
"""

import asyncio
from datetime import UTC, datetime
import json
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from fraud_detection.core.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Thread-safe WebSocket client registry and concurrent broadcast hub."""

    def __init__(self) -> None:
        """Initialize connection registry and operational counters."""
        self._active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._start_time: float = time.monotonic()
        self._total_broadcasts: int = 0
        self._total_frames_delivered: int = 0

    @property
    def active_count(self) -> int:
        """Return the count of currently connected active WebSocket clients."""
        return len(self._active_connections)

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept an inbound WebSocket handshake and register the client.

        Args:
            websocket: Incoming client WebSocket connection.
        """
        await websocket.accept()
        async with self._lock:
            self._active_connections.add(websocket)

        client_host = getattr(websocket.client, "host", "unknown")
        client_port = getattr(websocket.client, "port", "unknown")
        logger.info(
            "WebSocket client connected",
            extra={
                "client": f"{client_host}:{client_port}",
                "active_connections": len(self._active_connections),
            },
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Unregister a disconnected or terminated WebSocket client.

        Args:
            websocket: Terminated WebSocket client.
        """
        async with self._lock:
            self._active_connections.discard(websocket)

        client_host = getattr(websocket.client, "host", "unknown")
        logger.info(
            "WebSocket client disconnected",
            extra={
                "client": client_host,
                "active_connections": len(self._active_connections),
            },
        )

    async def broadcast_json(self, payload: dict[str, Any] | str) -> int:
        """
        Concurrently broadcast a JSON message frame to all active WebSocket clients.

        Uses asyncio.gather with return_exceptions=True to ensure that a slow or
        broken client socket does not block or fail message delivery to others.
        Stale/broken sockets are automatically purged from the registry.

        Args:
            payload: Python dictionary or pre-serialized JSON string.

        Returns:
            Count of clients that successfully received the message frame.
        """
        if not self._active_connections:
            return 0

        # Snapshot current connection set under lock
        async with self._lock:
            clients = list(self._active_connections)

        if not clients:
            return 0

        text_data = json.dumps(payload) if isinstance(payload, dict) else payload

        async def _send_to_client(ws: WebSocket) -> WebSocket | None:
            try:
                await ws.send_text(text_data)
                return None
            except (WebSocketDisconnect, RuntimeError, ConnectionResetError, OSError):
                return ws
            except Exception as exc:
                logger.warning("Unexpected WebSocket transmission error", extra={"error": str(exc)})
                return ws

        # Concurrently push to all clients
        results = await asyncio.gather(
            *[_send_to_client(ws) for ws in clients], return_exceptions=True
        )

        failed_sockets: list[WebSocket] = []
        delivered_count = 0

        for res in results:
            if res is None:
                delivered_count += 1
            elif isinstance(res, Exception):
                pass
            else:
                failed_sockets.append(res)

        # Purge dead sockets from active pool
        if failed_sockets:
            async with self._lock:
                for dead_ws in failed_sockets:
                    self._active_connections.discard(dead_ws)
            logger.debug(
                "Purged disconnected WebSocket clients",
                extra={
                    "purged": len(failed_sockets),
                    "remaining": len(self._active_connections),
                },
            )

        self._total_broadcasts += 1
        self._total_frames_delivered += delivered_count
        return delivered_count

    def get_metrics(self) -> dict[str, Any]:
        """
        Retrieve operational telemetry for active WebSocket clients.

        Returns:
            Dictionary containing connection count, message volumes, and uptime.
        """
        uptime_sec = time.monotonic() - self._start_time
        return {
            "active_clients": len(self._active_connections),
            "total_broadcasts": self._total_broadcasts,
            "total_frames_delivered": self._total_frames_delivered,
            "uptime_seconds": round(uptime_sec, 2),
            "timestamp": datetime.now(UTC).isoformat(),
        }


# Global singleton connection manager instance
manager = ConnectionManager()
