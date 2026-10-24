"""Unit tests for WebSocket ConnectionManager concurrent broadcast and lifecycle."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketDisconnect

from fraud_detection.api.websocket_manager import ConnectionManager


class MockWebSocket:
    """Mock WebSocket client with configurable send behavior."""

    def __init__(
        self, host: str = "127.0.0.1", port: int = 8000, should_fail: bool = False
    ) -> None:
        self.client = type("Client", (), {"host": host, "port": port})()
        self.should_fail = should_fail
        self.sent_messages: list[str] = []
        self.accept = AsyncMock()
        self.close = AsyncMock()

    async def send_text(self, data: str) -> None:
        if self.should_fail:
            raise WebSocketDisconnect(code=1001)
        self.sent_messages.append(data)


@pytest.mark.asyncio
class TestConnectionManager:
    """Test suite verifying ConnectionManager concurrency, purging, and metrics."""

    async def test_client_connect_and_disconnect(self) -> None:
        """Verify client registration and unregistration lifecycle."""
        mgr = ConnectionManager()
        ws1 = MockWebSocket(host="client1", port=1001)

        await mgr.connect(ws1)  # type: ignore[arg-type]
        assert mgr.active_count == 1
        ws1.accept.assert_awaited_once()

        await mgr.disconnect(ws1)  # type: ignore[arg-type]
        assert mgr.active_count == 0

    async def test_concurrent_broadcast_to_multiple_clients(self) -> None:
        """Verify concurrent message delivery across multiple connected clients."""
        mgr = ConnectionManager()
        ws_clients = [MockWebSocket(host=f"client_{i}", port=2000 + i) for i in range(5)]

        for ws in ws_clients:
            await mgr.connect(ws)  # type: ignore[arg-type]

        assert mgr.active_count == 5

        payload: dict[str, Any] = {
            "event_type": "FRAUD_ALERT",
            "transaction_ref": "tx_mock_123",
            "risk_score": 0.892,
            "status": "REJECTED",
        }

        delivered = await mgr.broadcast_json(payload)
        assert delivered == 5

        for ws in ws_clients:
            assert len(ws.sent_messages) == 1
            assert "tx_mock_123" in ws.sent_messages[0]
            assert "0.892" in ws.sent_messages[0]

    async def test_stale_and_dead_connection_purging(self) -> None:
        """Verify broken client sockets are automatically purged without failing broadcast to healthy sockets."""
        mgr = ConnectionManager()
        healthy_ws1 = MockWebSocket(host="healthy1", port=3001, should_fail=False)
        failing_ws = MockWebSocket(host="broken", port=3002, should_fail=True)
        healthy_ws2 = MockWebSocket(host="healthy2", port=3003, should_fail=False)

        await mgr.connect(healthy_ws1)  # type: ignore[arg-type]
        await mgr.connect(failing_ws)  # type: ignore[arg-type]
        await mgr.connect(healthy_ws2)  # type: ignore[arg-type]
        assert mgr.active_count == 3

        payload = {"status": "FLAGGED", "transaction_ref": "tx_test_456"}
        delivered = await mgr.broadcast_json(payload)

        # 2 healthy clients received the message
        assert delivered == 2
        assert len(healthy_ws1.sent_messages) == 1
        assert len(healthy_ws2.sent_messages) == 1

        # The failing client must be automatically purged
        assert mgr.active_count == 2
        assert failing_ws not in mgr._active_connections

    async def test_broadcast_with_no_clients(self) -> None:
        """Verify broadcast returns 0 when no clients are registered."""
        mgr = ConnectionManager()
        delivered = await mgr.broadcast_json({"test": "empty"})
        assert delivered == 0

    async def test_operational_metrics(self) -> None:
        """Verify operational telemetry metrics retrieval."""
        mgr = ConnectionManager()
        ws = MockWebSocket(host="metrics_client", port=4001)
        await mgr.connect(ws)  # type: ignore[arg-type]

        await mgr.broadcast_json({"ping": "pong"})
        metrics = mgr.get_metrics()

        assert metrics["active_clients"] == 1
        assert metrics["total_broadcasts"] == 1
        assert metrics["total_frames_delivered"] == 1
        assert metrics["uptime_seconds"] >= 0.0
        assert "timestamp" in metrics
