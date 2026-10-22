"""Unit tests for the Real-Time Kafka Fraud Consumer Worker."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fraud_detection.schemas.transaction import TransactionEvent
from fraud_detection.storage.redis_feature_store import RedisFeatureStore
from fraud_detection.streaming.consumer import FraudConsumer


@pytest.fixture
def mock_redis_store() -> RedisFeatureStore:
    """Create isolated in-memory Redis feature store for consumer testing."""
    return RedisFeatureStore(mock_mode=True)


@pytest.fixture
def fraud_consumer(mock_redis_store: RedisFeatureStore) -> FraudConsumer:
    """Create a FraudConsumer instance in mock mode."""
    return FraudConsumer(mock_mode=True, redis_store=mock_redis_store)


class TestFraudConsumer:
    """Validate core consumer pipeline processing, rules, ML inference, and alerts."""

    def test_consumer_initialization(self, fraud_consumer: FraudConsumer) -> None:
        assert fraud_consumer.mock_mode is True
        assert fraud_consumer.topic == "transactions"
        assert fraud_consumer.consumer_group == "fraud-inference-engine"
        assert fraud_consumer.processed_count == 0

    @pytest.mark.asyncio
    async def test_process_valid_legitimate_transaction(
        self,
        fraud_consumer: FraudConsumer,
    ) -> None:
        user_id = uuid4()
        account_id = uuid4()
        now = datetime.now(UTC)

        event = TransactionEvent(
            transaction_id=f"tx_{uuid4().hex[:12]}",
            user_id=user_id,
            account_id=account_id,
            amount=42.50,
            currency="USD",
            merchant_category="grocery",
            merchant_name="Trader Joe's",
            location_country="US",
            location_city="New York",
            location_lat=40.7128,
            location_lon=-74.0060,
            device_id="dev_phone_01",
            ip_address="192.168.1.1",
            timestamp=now,
            is_foreign_transaction=False,
            is_new_device=False,
        )

        # Cold start warmup
        _ = await fraud_consumer.process_raw_message(event.model_dump_json())

        # Steady-state evaluation
        event_steady = event.model_copy(update={"transaction_id": f"tx_{uuid4().hex[:12]}"})
        decision = await fraud_consumer.process_raw_message(event_steady.model_dump_json())
        assert decision is not None
        assert decision["transaction_id"] == event_steady.transaction_id
        assert decision["user_id"] == str(user_id)
        assert decision["status"] in ("APPROVED", "FLAGGED", "REJECTED")
        assert 0.0 <= decision["risk_score"] <= 1.0
        assert decision["total_latency_ms"] < 25.0
        assert fraud_consumer.processed_count == 2
        assert fraud_consumer.dlq_count == 0

    @pytest.mark.asyncio
    async def test_process_corrupt_payload_routes_to_dlq(
        self,
        fraud_consumer: FraudConsumer,
    ) -> None:
        # Invalid JSON
        corrupt_raw = b"{invalid_json_payload: null,"
        res = await fraud_consumer.process_raw_message(corrupt_raw)

        assert res is None
        assert fraud_consumer.dlq_count == 1
        assert fraud_consumer.processed_count == 0

        # Valid JSON but missing required fields
        incomplete_json = json.dumps({"amount": 100.0, "currency": "USD"})
        res2 = await fraud_consumer.process_raw_message(incomplete_json)

        assert res2 is None
        assert fraud_consumer.dlq_count == 2
        assert fraud_consumer.processed_count == 0

    @pytest.mark.asyncio
    async def test_process_velocity_burst_triggers_rejection(
        self,
        fraud_consumer: FraudConsumer,
    ) -> None:
        user_id = uuid4()
        account_id = uuid4()
        now = datetime.now(UTC)

        # Ingest 7 rapid micro transactions within 10 seconds
        for i in range(7):
            ev = TransactionEvent(
                transaction_id=f"tx_micro_{i}_{uuid4().hex[:8]}",
                user_id=user_id,
                account_id=account_id,
                amount=2.0,
                merchant_category="retail",
                merchant_name="Online Store",
                location_country="US",
                timestamp=now + timedelta(seconds=i * 1.0),
            )
            d = await fraud_consumer.process_raw_message(ev.model_dump_json())
            assert d is not None

        # 8th transaction hits RULE_01 (tx_count_1m >= 8)
        ev_burst = TransactionEvent(
            transaction_id=f"tx_burst_{uuid4().hex[:8]}",
            user_id=user_id,
            account_id=account_id,
            amount=2.0,
            merchant_category="retail",
            merchant_name="Online Store",
            location_country="US",
            timestamp=now + timedelta(seconds=8.0),
        )
        decision = await fraud_consumer.process_raw_message(ev_burst.model_dump_json())

        assert decision is not None
        assert decision["status"] == "REJECTED"
        assert decision["risk_score"] == 1.0
        assert "RULE_01" in decision["rule_violations"]
        assert len(fraud_consumer.published_alerts) >= 1

    @pytest.mark.asyncio
    async def test_process_impossible_travel_triggers_rejection(
        self,
        fraud_consumer: FraudConsumer,
    ) -> None:
        user_id = uuid4()
        account_id = uuid4()
        t0 = datetime.now(UTC)

        # Legitimate card-present transaction in Tokyo
        ev_tokyo = TransactionEvent(
            transaction_id=f"tx_tokyo_{uuid4().hex[:8]}",
            user_id=user_id,
            account_id=account_id,
            amount=50.0,
            merchant_category="retail",
            merchant_name="Tokyo Ginza",
            location_country="JP",
            location_city="Tokyo",
            location_lat=35.6762,
            location_lon=139.6503,
            timestamp=t0,
        )
        await fraud_consumer.process_raw_message(ev_tokyo.model_dump_json())

        # Impossible charge in London 3 minutes later
        t1 = t0 + timedelta(minutes=3)
        ev_london = TransactionEvent(
            transaction_id=f"tx_london_{uuid4().hex[:8]}",
            user_id=user_id,
            account_id=account_id,
            amount=850.0,
            merchant_category="jewelry",
            merchant_name="London Luxury",
            location_country="GB",
            location_city="London",
            location_lat=51.5074,
            location_lon=-0.1278,
            timestamp=t1,
        )
        decision = await fraud_consumer.process_raw_message(ev_london.model_dump_json())

        assert decision is not None
        assert decision["status"] == "REJECTED"
        assert decision["risk_score"] == 1.0
        assert "RULE_03" in decision["rule_violations"]
        assert any(
            a["transaction_id"] == ev_london.transaction_id for a in fraud_consumer.published_alerts
        )

    @pytest.mark.asyncio
    async def test_process_sanctioned_country_triggers_rejection(
        self,
        fraud_consumer: FraudConsumer,
    ) -> None:
        user_id = uuid4()
        account_id = uuid4()

        ev = TransactionEvent(
            transaction_id=f"tx_sanctioned_{uuid4().hex[:8]}",
            user_id=user_id,
            account_id=account_id,
            amount=150.0,
            merchant_category="crypto",
            merchant_name="Offshore Hub",
            location_country="CU",  # Cuba (Sanctioned)
            timestamp=datetime.now(UTC),
        )
        decision = await fraud_consumer.process_raw_message(ev.model_dump_json())

        assert decision is not None
        assert decision["status"] == "REJECTED"
        assert decision["risk_score"] == 1.0
        assert "RULE_04" in decision["rule_violations"]

    @pytest.mark.asyncio
    async def test_process_high_value_triggers_flagged(
        self,
        fraud_consumer: FraudConsumer,
    ) -> None:
        user_id = uuid4()
        account_id = uuid4()

        ev = TransactionEvent(
            transaction_id=f"tx_large_{uuid4().hex[:8]}",
            user_id=user_id,
            account_id=account_id,
            amount=32000.0,  # >= $25,000 threshold
            merchant_category="jewelry",
            merchant_name="Cartier Luxury",
            location_country="US",
            timestamp=datetime.now(UTC),
        )
        decision = await fraud_consumer.process_raw_message(ev.model_dump_json())

        assert decision is not None
        assert decision["status"] in ("FLAGGED", "REJECTED")
        assert "RULE_02" in decision["rule_violations"]

    @pytest.mark.asyncio
    async def test_process_nocturnal_device_triggers_flagged(
        self,
        fraud_consumer: FraudConsumer,
    ) -> None:
        user_id = uuid4()
        account_id = uuid4()

        # 03:30 AM UTC
        nocturnal_time = datetime.now(UTC).replace(hour=3, minute=30, second=0)

        ev = TransactionEvent(
            transaction_id=f"tx_nocturnal_{uuid4().hex[:8]}",
            user_id=user_id,
            account_id=account_id,
            amount=3500.0,
            merchant_category="crypto",
            merchant_name="Binance Global",
            location_country="US",
            device_id="dev_new_unknown_99",
            is_new_device=True,
            timestamp=nocturnal_time,
        )
        decision = await fraud_consumer.process_raw_message(ev.model_dump_json())

        assert decision is not None
        assert decision["status"] in ("FLAGGED", "REJECTED")
        assert "RULE_05" in decision["rule_violations"]

    @pytest.mark.asyncio
    async def test_on_decision_callback_invoked(
        self,
        mock_redis_store: RedisFeatureStore,
    ) -> None:
        received_decisions: list[dict] = []

        def callback(decision: dict) -> None:
            received_decisions.append(decision)

        consumer = FraudConsumer(
            mock_mode=True,
            redis_store=mock_redis_store,
            on_decision=callback,
        )

        ev = TransactionEvent(
            transaction_id=f"tx_cb_{uuid4().hex[:8]}",
            user_id=uuid4(),
            account_id=uuid4(),
            amount=29.99,
            merchant_category="restaurants",
            merchant_name="Starbucks",
            location_country="US",
            timestamp=datetime.now(UTC),
        )

        await consumer.process_raw_message(ev.model_dump_json())
        assert len(received_decisions) == 1
        assert received_decisions[0]["transaction_id"] == ev.transaction_id

    @pytest.mark.asyncio
    async def test_consumer_stop_cleanly(self, fraud_consumer: FraudConsumer) -> None:
        fraud_consumer.running = True
        await fraud_consumer.stop()
        assert fraud_consumer.running is False
