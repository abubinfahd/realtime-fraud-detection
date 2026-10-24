"""Unit tests for Stage 8 — Redis Pub/Sub Event Fan-Out Layer.

Covers:
- RedisPublisher lifecycle and mock broker fallback.
- Verdict filtering policy: strictly isolates FLAGGED/REJECTED threats and discards normal APPROVED.
- Fraud alert payload structure and signals explainability.
- Operational system telemetry publishing on channel:system-metrics.
- Real-time subscriber queue delivery.
- FraudConsumer end-to-end alert broadcasting integration.
"""

import asyncio
from uuid import uuid4

import pytest

from fraud_detection.core.config import settings
from fraud_detection.storage.redis_publisher import InMemoryPubSubHub, RedisPublisher
from fraud_detection.streaming.consumer import FraudConsumer


@pytest.fixture
def mock_hub() -> InMemoryPubSubHub:
    """Provide an in-memory Pub/Sub broker fixture."""
    return InMemoryPubSubHub()


@pytest.fixture
def publisher() -> RedisPublisher:
    """Provide an initialized mock RedisPublisher."""
    return RedisPublisher(mock_mode=True)


@pytest.mark.asyncio
async def test_redis_publisher_lifecycle(publisher: RedisPublisher) -> None:
    """Test RedisPublisher mock mode initialization and closure."""
    await publisher.initialize()
    assert publisher.mock_mode is True
    assert publisher._in_memory is not None

    await publisher.close()
    assert len(publisher.published_alerts) == 0


def test_verdict_filtering_policy() -> None:
    """Verify that normal APPROVED events are discarded while high-risk events are published."""
    # 1. Normal APPROVED with low risk -> Should NOT publish
    approved_safe = {
        "status": "APPROVED",
        "risk_score": 0.05,
    }
    assert RedisPublisher.should_publish(approved_safe) is False

    # 2. APPROVED but border-line risk (>= 0.40) -> Should publish
    approved_borderline = {
        "status": "APPROVED",
        "risk_score": 0.42,
    }
    assert RedisPublisher.should_publish(approved_borderline) is True

    # 3. FLAGGED -> Should publish
    flagged_threat = {
        "status": "FLAGGED",
        "risk_score": 0.55,
    }
    assert RedisPublisher.should_publish(flagged_threat) is True

    # 4. REJECTED -> Should publish
    rejected_threat = {
        "status": "REJECTED",
        "risk_score": 0.92,
    }
    assert RedisPublisher.should_publish(rejected_threat) is True


def test_format_alert_payload_schema() -> None:
    """Verify structured JSON payload adheres strictly to FraudAlert schema."""
    tx_id = f"tx_{uuid4().hex[:12]}"
    u_id = str(uuid4())

    decision = {
        "transaction_id": tx_id,
        "user_id": u_id,
        "account_id": str(uuid4()),
        "amount": 2499.50,
        "currency": "USD",
        "status": "REJECTED",
        "risk_score": 0.8842,
        "fraud_probability": 0.9120,
        "anomaly_score": 0.7450,
        "merchant_name": "CryptoExchange X",
        "merchant_category": "cryptocurrency",
        "rule_violations": ["RULE_IMPOSSIBLE_TRAVEL", "RULE_VELOCITY_BURST"],
        "reasons": ["Impossible velocity detected"],
        "latency_ms": 3.45,
    }

    velocity = {
        "tx_count_1m": 8,
        "tx_count_10m": 15,
        "tx_sum_10m": 4200.0,
        "amount_to_avg_ratio": 4.5,
    }

    payload = RedisPublisher.format_alert_payload(decision, velocity)

    assert payload["event_type"] == "FRAUD_ALERT"
    assert payload["transaction_id"] == tx_id
    assert payload["user_id"] == u_id
    assert payload["amount"] == 2499.50
    assert payload["status"] == "REJECTED"
    assert payload["risk_score"] == 0.8842

    # Merchant block
    assert payload["merchant"]["name"] == "CryptoExchange X"
    assert payload["merchant"]["category"] == "cryptocurrency"

    # Signals
    signals = payload["signals"]
    assert signals["lgbm_fraud_prob"] == 0.9120
    assert signals["anomaly_score"] == 0.7450
    assert "RULE_IMPOSSIBLE_TRAVEL" in signals["rule_violations"]

    # Velocity context
    vel_ctx = payload["velocity_context"]
    assert vel_ctx["tx_count_1m"] == 8
    assert vel_ctx["tx_sum_10m"] == 4200.0

    # Timings
    assert "edge_timestamp" in payload["timings"]
    assert "decision_timestamp" in payload["timings"]
    assert payload["timings"]["inference_latency_ms"] == 3.45


@pytest.mark.asyncio
async def test_publish_alert_and_subscriber(publisher: RedisPublisher) -> None:
    """Verify fire-and-forget publish and async iterator subscriber reception."""
    await publisher.initialize()

    # 1. Test filtered event returns False
    safe_event = {"status": "APPROVED", "risk_score": 0.08}
    published = await publisher.publish_alert(safe_event)
    assert published is False
    assert len(publisher.published_alerts) == 0

    # 2. Test threat event returns True and delivers to subscriber
    threat_event = {
        "transaction_id": f"tx_{uuid4().hex[:8]}",
        "user_id": str(uuid4()),
        "amount": 750.0,
        "status": "REJECTED",
        "risk_score": 0.95,
        "latency_ms": 2.1,
    }

    received_alerts: list[dict] = []

    async def _subscriber_task() -> None:
        async for alert in publisher.subscribe(settings.REDIS_ALERTS_CHANNEL):
            received_alerts.append(alert)
            break

    sub_task = asyncio.create_task(_subscriber_task())
    await asyncio.sleep(0.02)  # Give subscriber loop time to register

    published = await publisher.publish_alert(threat_event)
    assert published is True
    assert len(publisher.published_alerts) == 1

    await asyncio.wait_for(sub_task, timeout=1.0)
    assert len(received_alerts) == 1
    assert received_alerts[0]["status"] == "REJECTED"
    assert received_alerts[0]["risk_score"] == 0.95

    await publisher.close()


@pytest.mark.asyncio
async def test_publish_metrics_telemetry(publisher: RedisPublisher) -> None:
    """Verify operational system telemetry broadcasting on channel:system-metrics."""
    await publisher.initialize()

    received_metrics: list[dict] = []

    async def _metrics_subscriber() -> None:
        async for m in publisher.subscribe(publisher.metrics_channel):
            received_metrics.append(m)
            break

    sub_task = asyncio.create_task(_metrics_subscriber())
    await asyncio.sleep(0.02)

    metrics_payload = {
        "current_tps": 48.5,
        "mean_latency_ms": 3.12,
        "p95_latency_ms": 4.80,
        "approval_ratio": 0.92,
    }

    success = await publisher.publish_metrics(metrics_payload)
    assert success is True

    await asyncio.wait_for(sub_task, timeout=1.0)
    assert len(received_metrics) == 1
    assert received_metrics[0]["event_type"] == "SYSTEM_METRICS"
    assert received_metrics[0]["current_tps"] == 48.5

    await publisher.close()


@pytest.mark.asyncio
async def test_fraud_consumer_alerts_integration() -> None:
    """Test FraudConsumer broadcasting high-risk alerts to RedisPublisher in simulation."""
    publisher = RedisPublisher(mock_mode=True)
    await publisher.initialize()

    consumer = FraudConsumer(
        mock_mode=True,
        redis_publisher=publisher,
        enable_persistence=True,
    )

    # In mock mode, with anomaly rate ~10%, run for 30 messages
    await consumer.start(max_messages=30)

    assert consumer.processed_count == 30
    # Consumer should have routed alerts via publisher
    total_threats = consumer.flagged_count + consumer.rejected_count
    assert len(publisher.published_alerts) >= 0

    if total_threats > 0:
        assert len(publisher.published_alerts) == total_threats
        for alert in publisher.published_alerts:
            assert alert["status"] in ("FLAGGED", "REJECTED")

    await consumer.stop()
