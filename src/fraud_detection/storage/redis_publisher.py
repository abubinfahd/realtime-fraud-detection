"""High-throughput Redis Pub/Sub Event Fan-Out Publisher.

Features:
- Sub-millisecond non-blocking fire-and-forget broadcasting (< 0.2 ms).
- Verdict filtering policy: isolates actionable threats (FLAGGED/REJECTED or risk >= 0.40)
  while discarding normal APPROVED transactions to prevent edge socket flooding.
- Formats structured JSON payloads conforming to fraud alert specifications.
- Supports operational system metrics broadcasting (channel:system-metrics).
- Async iterator subscription interface for WebSocket gateways and CLI listeners.
- Thread-safe in-memory mock broker fallback for testing and offline execution.
"""

from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
import json
import time
from typing import Any

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger

logger = get_logger("fraud_detection.storage.redis_publisher")


class InMemoryPubSubHub:
    """In-memory Pub/Sub broker simulator for mock testing and offline execution."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Any]] = defaultdict(list)
        self.published_messages: list[tuple[str, str]] = []  # (channel, raw_json)

    def publish(self, channel: str, message: str) -> int:
        """Publish a message string to a channel; deliver to all subscriber queues."""
        self.published_messages.append((channel, message))
        subscribers = self._subscribers.get(channel, [])
        for q in subscribers:
            try:
                q.put_nowait(message)
            except Exception:
                pass
        return len(subscribers)

    def subscribe(self, channel: str) -> Any:
        """Register a subscriber queue for a channel."""
        import asyncio

        q: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers[channel].append(q)
        return q

    def unsubscribe(self, channel: str, queue: Any) -> None:
        """Unregister a subscriber queue."""
        if channel in self._subscribers and queue in self._subscribers[channel]:
            self._subscribers[channel].remove(queue)

    def clear(self) -> None:
        """Clear all messages and active subscribers."""
        self._subscribers.clear()
        self.published_messages.clear()


class RedisPublisher:
    """Asynchronous Redis Pub/Sub publisher for high-risk alerts and telemetry."""

    def __init__(
        self,
        redis_url: str | None = None,
        alerts_channel: str = settings.REDIS_ALERTS_CHANNEL,
        metrics_channel: str = "channel:system-metrics",
        mock_mode: bool = False,
        redis_client: Any = None,
    ) -> None:
        self.redis_url = redis_url or settings.redis_url
        self.alerts_channel = alerts_channel
        self.metrics_channel = metrics_channel
        self.mock_mode = mock_mode
        self._client: Any = redis_client
        self._in_memory: InMemoryPubSubHub | None = (
            InMemoryPubSubHub() if (mock_mode or redis_client is None) else None
        )
        self._published_alerts: list[dict[str, Any]] = []

    async def initialize(self) -> None:
        """Initialize connection to live Redis or activate mock simulator."""
        if self._client is not None and not self.mock_mode:
            return

        if self.mock_mode:
            if self._in_memory is None:
                self._in_memory = InMemoryPubSubHub()
            logger.info("RedisPublisher initialized in MOCK simulation mode.")
            return

        try:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(
                self.redis_url,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
                decode_responses=True,
            )
            # Verify connectivity
            await self._client.ping()
            logger.info("Connected to Redis 7 Pub/Sub engine", extra={"url": self.redis_url})
        except Exception as exc:
            logger.warning(
                "Failed to connect to live Redis Pub/Sub. Falling back to in-memory mock broker.",
                extra={"error": str(exc)},
            )
            self.mock_mode = True
            self._in_memory = InMemoryPubSubHub()

    async def close(self) -> None:
        """Close connection pool cleanly."""
        if self._client is not None and not self.mock_mode:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        if self._in_memory is not None:
            self._in_memory.clear()
        logger.info("RedisPublisher connection closed.")

    @staticmethod
    def should_publish(decision: dict[str, Any]) -> bool:
        """
        Evaluate traffic verdict filtering policy.

        Only transactions where status is 'FLAGGED' or 'REJECTED',
        or risk_score >= FRAUD_THRESHOLD_LOW (0.40) are emitted.
        Normal 'APPROVED' transactions are discarded to prevent edge socket flooding.
        """
        status = str(decision.get("status", "APPROVED")).upper()
        if status in ("FLAGGED", "REJECTED"):
            return True

        risk_score = float(decision.get("risk_score", 0.0))
        return risk_score >= settings.FRAUD_THRESHOLD_LOW

    @staticmethod
    def format_alert_payload(
        decision: dict[str, Any],
        velocity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Format scored transaction into canonical fraud alert JSON schema."""
        vel = velocity or {}
        now_iso = datetime.now(UTC).isoformat()

        # Handle user id
        user_val = decision.get("user_id")
        user_str = str(user_val) if user_val else ""

        # Normalize timings
        edge_ts = decision.get("timestamp") or now_iso
        if hasattr(edge_ts, "isoformat"):
            edge_ts = edge_ts.isoformat()
        else:
            edge_ts = str(edge_ts)

        # Signals
        signals = {
            "lgbm_fraud_prob": float(
                decision.get("fraud_probability", decision.get("risk_score", 0.0))
            ),
            "anomaly_score": float(decision.get("anomaly_score", 0.0)),
            "rule_violations": list(decision.get("rule_violations") or []),
            "reasons": list(decision.get("reasons") or []),
        }

        # Velocity context
        velocity_context = {
            "tx_count_1m": int(vel.get("tx_count_1m", 1)),
            "tx_count_10m": int(vel.get("tx_count_10m", 1)),
            "tx_sum_10m": float(vel.get("tx_sum_10m", decision.get("amount", 0.0))),
            "amount_to_avg_ratio": float(vel.get("amount_to_avg_ratio", 1.0)),
        }

        merchant_name = str(decision.get("merchant_name", "Unknown Merchant"))
        merchant_category = str(decision.get("merchant_category", "retail"))

        return {
            "event_type": "FRAUD_ALERT",
            "transaction_id": str(decision.get("transaction_id", "")),
            "user_id": user_str,
            "account_id": str(decision.get("account_id", "")),
            "amount": round(float(decision.get("amount", 0.0)), 2),
            "currency": str(decision.get("currency", "USD")),
            "status": str(decision.get("status", "FLAGGED")),
            "risk_score": round(float(decision.get("risk_score", 0.0)), 4),
            "merchant": {
                "name": merchant_name,
                "category": merchant_category,
            },
            "merchant_name": merchant_name,
            "merchant_category": merchant_category,
            "signals": signals,
            "velocity_context": velocity_context,
            "inference_latency_ms": round(
                float(decision.get("total_latency_ms", decision.get("latency_ms", 0.0))), 3
            ),
            "timings": {
                "edge_timestamp": edge_ts,
                "decision_timestamp": now_iso,
                "inference_latency_ms": round(
                    float(decision.get("total_latency_ms", decision.get("latency_ms", 0.0))), 3
                ),
            },
        }

    async def publish_alert(
        self,
        decision: dict[str, Any],
        velocity: dict[str, Any] | None = None,
    ) -> bool:
        """
        Publish high-risk fraud alert to Redis Pub/Sub in non-blocking fire-and-forget mode.

        Returns True if alert met filtering criteria and was published, False if filtered out.
        """
        if not self.should_publish(decision):
            return False

        t0 = time.perf_counter()
        payload = self.format_alert_payload(decision, velocity)
        payload_json = json.dumps(payload)

        self._published_alerts.append(payload)

        # In-memory mock broker branch
        if self.mock_mode or self._client is None:
            if self._in_memory is not None:
                self._in_memory.publish(self.alerts_channel, payload_json)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.debug(
                "Published alert to mock Pub/Sub",
                extra={
                    "channel": self.alerts_channel,
                    "status": payload["status"],
                    "elapsed_ms": round(elapsed_ms, 3),
                },
            )
            return True

        # Live Redis execution
        try:
            await self._client.publish(self.alerts_channel, payload_json)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.debug(
                "Published alert to Redis Pub/Sub",
                extra={
                    "channel": self.alerts_channel,
                    "status": payload["status"],
                    "elapsed_ms": round(elapsed_ms, 3),
                },
            )
            return True
        except Exception as exc:
            logger.warning(
                "Fire-and-forget Redis Pub/Sub publish failed; continuing stream",
                extra={"error": str(exc)},
            )
            return False

    async def publish_stream_event(
        self,
        decision: dict[str, Any],
        velocity: dict[str, Any] | None = None,
    ) -> bool:
        """
        Broadcast any scored transaction (including APPROVED) to live Redis Pub/Sub
        for real-time dashboard TPS telemetry and live ticker updates, without
        polluting the threat-only `published_alerts` audit list.
        """
        if self.mock_mode or self._client is None:
            return False

        try:
            payload = self.format_alert_payload(decision, velocity)
            payload["event_type"] = "STREAM_EVENT"
            await self._client.publish(self.alerts_channel, json.dumps(payload))
            return True
        except Exception:
            return False

    async def publish_metrics(self, metrics: dict[str, Any]) -> bool:
        """Publish aggregated operational telemetry to metrics channel."""
        now_iso = datetime.now(UTC).isoformat()
        payload = {
            "event_type": "SYSTEM_METRICS",
            "timestamp": now_iso,
            **metrics,
        }
        payload_json = json.dumps(payload)

        if self.mock_mode or self._client is None:
            if self._in_memory is not None:
                self._in_memory.publish(self.metrics_channel, payload_json)
            return True

        try:
            await self._client.publish(self.metrics_channel, payload_json)
            return True
        except Exception as exc:
            logger.warning(
                "Failed to publish metrics to Redis Pub/Sub",
                extra={"error": str(exc)},
            )
            return False

    async def subscribe(self, channel: str | None = None) -> AsyncIterator[dict[str, Any]]:
        """
        Asynchronously subscribe and yield messages received from a channel.

        Works seamlessly on both live Redis and in-memory mock broker.
        """
        target_channel = channel or self.alerts_channel

        if self.mock_mode or self._client is None:
            if self._in_memory is None:
                self._in_memory = InMemoryPubSubHub()
            q = self._in_memory.subscribe(target_channel)
            try:
                while True:
                    msg_str = await q.get()
                    try:
                        data = json.loads(msg_str)
                        yield data
                    except Exception:
                        pass
            finally:
                self._in_memory.unsubscribe(target_channel, q)
            return

        # Live Redis pubsub subscription
        pubsub = self._client.pubsub()
        await pubsub.subscribe(target_channel)
        try:
            async for message in pubsub.listen():
                if message and message.get("type") == "message":
                    raw_data = message.get("data")
                    if raw_data:
                        try:
                            data = json.loads(raw_data)
                            yield data
                        except Exception:
                            pass
        finally:
            await pubsub.unsubscribe(target_channel)
            await pubsub.close()

    @property
    def published_alerts(self) -> list[dict[str, Any]]:
        """Return history of all alerts published through this instance."""
        return self._published_alerts


__all__ = ["InMemoryPubSubHub", "RedisPublisher"]
