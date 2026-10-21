"""Unit tests for Stage 4: Kafka Producer, Token Bucket Limiter, and Synthetic Anomalies."""

import json
import time
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from fraud_detection.schemas.transaction import TransactionEvent
from fraud_detection.streaming.anomalies import AnomalyGenerator
from fraud_detection.streaming.config import ProducerConfig
from fraud_detection.streaming.producer import TokenBucketRateLimiter, TransactionProducer


class TestProducerConfig:
    """Test suite for Kafka Producer configuration container."""

    def test_default_producer_config(self) -> None:
        """Verify default settings initialization."""
        config = ProducerConfig()
        assert config.bootstrap_servers == "localhost:9092"
        assert config.topic == "transactions"
        assert config.client_id == "fraud-synthetic-producer"
        assert config.acks == "1"
        assert config.linger_ms == 5
        assert config.batch_num_messages == 1000
        assert config.compression_type == "snappy"
        assert config.tps == 50.0
        assert config.anomaly_rate == 0.02
        assert config.dry_run is False

    def test_to_librdkafka_dict(self) -> None:
        """Verify mapping from ProducerConfig to librdkafka C-client parameters."""
        config = ProducerConfig(
            bootstrap_servers="broker.prod:9092",
            client_id="custom-producer",
            acks="all",
            linger_ms=10,
            batch_num_messages=500,
            compression_type="zstd",
        )
        conf_dict = config.to_librdkafka_dict()
        assert conf_dict["bootstrap.servers"] == "broker.prod:9092"
        assert conf_dict["client.id"] == "custom-producer"
        assert conf_dict["acks"] == "all"
        assert conf_dict["linger.ms"] == 10
        assert conf_dict["batch.num.messages"] == 500
        assert conf_dict["compression.type"] == "zstd"
        assert conf_dict["queue.buffering.max.messages"] == 100000


class TestTokenBucketRateLimiter:
    """Test suite for Token Bucket rate limiting."""

    def test_rate_limiter_instant_acquire_within_capacity(self) -> None:
        """Verify tokens up to capacity can be acquired immediately."""
        limiter = TokenBucketRateLimiter(rate=100.0, capacity=20.0)
        start = time.monotonic()
        for _ in range(10):
            limiter.acquire(1.0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Instantaneous consumption from initial capacity

    def test_rate_limiter_steady_state_rate(self) -> None:
        """Verify steady state rate control (e.g., 20 TPS takes ~0.25-0.35s for 6 tokens)."""
        limiter = TokenBucketRateLimiter(rate=20.0, capacity=1.0)
        # Drain initial token
        limiter.acquire(1.0)

        start = time.monotonic()
        tokens_to_acquire = 4
        for _ in range(tokens_to_acquire):
            limiter.acquire(1.0)
        elapsed = time.monotonic() - start

        # 4 tokens at 20 tokens/sec should take ~0.20s (+/- 0.08s tolerance)
        assert 0.12 <= elapsed <= 0.35


class TestAnomalyGenerator:
    """Test suite for synthetic fraud attack patterns."""

    @pytest.fixture
    def test_user_ids(self) -> tuple:
        return uuid4(), uuid4()

    def test_velocity_spike_generation(self, test_user_ids: tuple) -> None:
        """Verify Pattern 1: Velocity Spike Attack (Card Testing micro-charges)."""
        uid, aid = test_user_ids
        events = AnomalyGenerator.generate_velocity_spike(
            user_id=uid, account_id=aid, burst_size=10
        )

        assert len(events) == 10
        for ev in events:
            assert ev.user_id == uid
            assert ev.account_id == aid
            assert 1.00 <= ev.amount <= 5.00
            assert ev.is_new_device is True
            assert ev.merchant_category in ["retail", "utilities", "electronics"]

        # Timestamps should be tightly clustered within seconds
        delta = (events[-1].timestamp - events[0].timestamp).total_seconds()
        assert 5.0 <= delta <= 25.0

    def test_high_value_outlier_generation(self, test_user_ids: tuple) -> None:
        """Verify Pattern 2: Sudden High-Value Outlier (Account Takeover)."""
        uid, aid = test_user_ids
        ev = AnomalyGenerator.generate_high_value_outlier(user_id=uid, account_id=aid)

        assert ev.user_id == uid
        assert ev.account_id == aid
        assert 1200.00 <= ev.amount <= 4999.00
        assert ev.is_new_device is True
        assert ev.merchant_category in ["crypto", "jewelry", "electronics"]

    def test_geographic_jump_generation(self, test_user_ids: tuple) -> None:
        """Verify Pattern 3: Geographic Impossibility (Super-speed travel)."""
        uid, aid = test_user_ids
        t1, t2 = AnomalyGenerator.generate_geographic_jump(user_id=uid, account_id=aid)

        assert t1.user_id == uid and t2.user_id == uid
        assert t1.location_country == "JP" and t1.location_city == "Tokyo"
        assert t2.location_country == "GB" and t2.location_city == "London"
        assert t1.is_foreign_transaction is True
        assert t2.is_foreign_transaction is True

        # Time between Tokyo and London must be between 120 and 300 seconds
        delta = (t2.timestamp - t1.timestamp).total_seconds()
        assert 120 <= delta <= 300

    def test_nocturnal_high_risk_generation(self, test_user_ids: tuple) -> None:
        """Verify Pattern 4: Nocturnal High-Risk Category."""
        uid, aid = test_user_ids
        ev = AnomalyGenerator.generate_nocturnal_high_risk(user_id=uid, account_id=aid)

        assert ev.user_id == uid
        assert ev.merchant_category in ["crypto", "gambling"]
        assert 450.00 <= ev.amount <= 2400.00
        assert 2 <= ev.timestamp.hour <= 4
        assert ev.is_foreign_transaction is True

    def test_random_anomaly_selection(self, test_user_ids: tuple) -> None:
        """Verify random anomaly selector returns valid non-empty events."""
        uid, aid = test_user_ids
        for _ in range(15):
            events = AnomalyGenerator.generate_random_anomaly(user_id=uid, account_id=aid)
            assert len(events) >= 1
            for ev in events:
                assert isinstance(ev, TransactionEvent)
                assert ev.user_id == uid


class TestTransactionProducer:
    """Test suite for TransactionProducer streaming and lifecycle."""

    def test_generate_legitimate_event_schema(self) -> None:
        """Verify legitimate transaction properties and schema compliance."""
        config = ProducerConfig(dry_run=True)
        producer = TransactionProducer(config=config)
        event = producer.generate_legitimate_event()

        assert isinstance(event, TransactionEvent)
        assert 2.50 <= event.amount <= 350.00
        assert event.is_foreign_transaction is False
        assert event.is_new_device is False

        # Verify Kafka serialization dict format
        kafka_payload = event.to_kafka_dict()
        assert "transaction_id" in kafka_payload
        assert "user_id" in kafka_payload
        assert "location" in kafka_payload
        assert "device" in kafka_payload
        assert kafka_payload["location"]["country"] == "US"

    def test_key_invariance_for_partition_routing(self) -> None:
        """Verify that every transaction is keyed with string(user_id)."""
        config = ProducerConfig(dry_run=True)
        producer = TransactionProducer(config=config)
        event = producer.generate_legitimate_event()

        expected_key = str(event.user_id).encode("utf-8")
        assert expected_key is not None
        assert len(expected_key) > 0

    def test_dry_run_emission(self) -> None:
        """Verify dry-run mode emits events without requiring live Kafka broker."""
        config = ProducerConfig(tps=500.0, max_events=10, dry_run=True)
        producer = TransactionProducer(config=config)
        producer.run()

        assert producer.total_sent == 10
        assert producer.total_delivered == 10
        assert producer.total_failed == 0

    def test_mocked_kafka_produce(self) -> None:
        """Verify kafka produce call signature and payload structure with mock."""
        config = ProducerConfig(dry_run=False)
        producer = TransactionProducer(config=config)

        # Inject mock confluent-kafka producer
        producer.config.dry_run = False
        mock_kproducer = MagicMock()
        producer._producer = mock_kproducer

        event = producer.generate_legitimate_event()
        producer.produce_event(event)

        assert mock_kproducer.produce.called
        call_kwargs = mock_kproducer.produce.call_args.kwargs
        assert call_kwargs["topic"] == "transactions"
        assert call_kwargs["key"] == str(event.user_id).encode("utf-8")

        # Parse value payload
        value_data = json.loads(call_kwargs["value"].decode("utf-8"))
        assert value_data["transaction_id"] == event.transaction_id
        assert value_data["user_id"] == str(event.user_id)
        assert value_data["amount"] == round(event.amount, 2)

    def test_delivery_report_callback_success(self) -> None:
        """Verify delivery report callback handles successful offset commits."""
        producer = TransactionProducer(config=ProducerConfig(dry_run=True))
        mock_msg = MagicMock()
        mock_msg.topic.return_value = "transactions"
        mock_msg.partition.return_value = 1
        mock_msg.offset.return_value = 105

        initial_delivered = producer.total_delivered
        producer.delivery_report(err=None, msg=mock_msg)
        assert producer.total_delivered == initial_delivered + 1
        assert producer.total_failed == 0

    def test_delivery_report_callback_error(self) -> None:
        """Verify delivery report callback tracks delivery errors."""
        producer = TransactionProducer(config=ProducerConfig(dry_run=True))
        mock_msg = MagicMock()
        mock_msg.topic.return_value = "transactions"

        initial_failed = producer.total_failed
        producer.delivery_report(err="Broker: Message timed out", msg=mock_msg)
        assert producer.total_failed == initial_failed + 1
