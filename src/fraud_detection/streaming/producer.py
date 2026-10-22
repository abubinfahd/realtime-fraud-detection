"""High-performance synthetic transaction Kafka producer.

Features:
- Precision Token Bucket rate limiting to guarantee configurable TPS.
- Automatic topic provisioning (3 partitions, keying by user_id).
- Intermittent anomaly injection (velocity bursts, impossible travel, account takeover).
- Asynchronous non-blocking delivery callbacks with error recovery.
- Safe graceful shutdown handling SIGINT/SIGTERM with producer.flush().
"""

import argparse
import json
import random
import signal
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.schemas.transaction import TransactionEvent
from fraud_detection.streaming.anomalies import AnomalyGenerator
from fraud_detection.streaming.config import ProducerConfig

logger = get_logger("fraud_detection.streaming.producer")

# Standard fixed user profiles matching database/init.sql fixtures
SEEDED_USERS: list[dict[str, Any]] = [
    {
        "user_id": UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"),
        "account_id": UUID("a1eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"),
        "name": "Alice Johnson",
        "city": "New York",
        "country": "US",
        "lat": 40.7128,
        "lon": -74.0060,
    },
    {
        "user_id": UUID("b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a22"),
        "account_id": UUID("b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22"),
        "name": "Bob Smith",
        "city": "Chicago",
        "country": "US",
        "lat": 41.8781,
        "lon": -87.6298,
    },
    {
        "user_id": UUID("c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a33"),
        "account_id": UUID("c1eebc99-9c0b-4ef8-bb6d-6bb9bd380a33"),
        "name": "Charlie Davis",
        "city": "San Francisco",
        "country": "US",
        "lat": 37.7749,
        "lon": -122.4194,
    },
]

LEGIT_CATEGORIES = ["grocery", "retail", "restaurants", "utilities", "entertainment"]
LEGIT_MERCHANTS_MAP = {
    "grocery": ["Walmart Supercenter", "Kroger", "Whole Foods Market", "Trader Joe's", "ALDI"],
    "retail": ["Target", "Amazon Fulfillment", "Best Buy", "Home Depot", "Macy's"],
    "restaurants": ["Starbucks Coffee", "McDonald's", "Chipotle Mexican Grill", "Subway"],
    "utilities": ["ConEdison Power", "AT&T Mobility", "Verizon Wireless", "Duke Energy"],
    "entertainment": ["Netflix Streaming", "Spotify Premium", "AMC Theatres", "Steam Store"],
}


class TokenBucketRateLimiter:
    """Accurate rate limiter that controls TPS using the token bucket algorithm."""

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self.rate = max(0.1, float(rate))
        self.capacity = capacity if capacity is not None else max(self.rate, 10.0)
        self.tokens = self.capacity
        self.last_update = time.monotonic()

    def acquire(self, tokens: float = 1.0) -> None:
        """Wait until requested tokens are available."""
        while True:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

            if self.tokens >= tokens:
                self.tokens -= tokens
                return

            sleep_duration = (tokens - self.tokens) / self.rate
            if sleep_duration > 0:
                time.sleep(sleep_duration)


class TransactionProducer:
    """Manages high-throughput synthetic stream publishing into Apache Kafka."""

    def __init__(self, config: ProducerConfig | None = None) -> None:
        self.config = config or ProducerConfig()
        self.rate_limiter = TokenBucketRateLimiter(rate=self.config.tps)
        self.stop_requested = False
        self.total_sent = 0
        self.total_delivered = 0
        self.total_failed = 0

        # Maintain a dynamic pool of synthetic users alongside seeded users
        self.user_pool = list(SEEDED_USERS)
        for _ in range(50):
            u_id = uuid4()
            a_id = uuid4()
            self.user_pool.append(
                {
                    "user_id": u_id,
                    "account_id": a_id,
                    "name": f"Synthetic User {u_id.hex[:6]}",
                    "city": "Austin",
                    "country": "US",
                    "lat": 30.2672,
                    "lon": -97.7431,
                }
            )

        self._producer: Any = None
        if not self.config.dry_run:
            self._init_kafka_producer()

    def _init_kafka_producer(self) -> None:
        """Initialize confluent-kafka Producer and ensure topic existence."""
        try:
            from confluent_kafka import Producer
            from confluent_kafka.admin import AdminClient, NewTopic
        except ImportError:
            logger.warning(
                "confluent-kafka not installed in current environment. "
                "Running in dry-run simulation mode."
            )
            self.config.dry_run = True
            return

        # 1. Ensure topic exists with 3 partitions
        try:
            admin = AdminClient({"bootstrap.servers": self.config.bootstrap_servers})
            metadata = admin.list_topics(timeout=5.0)
            if self.config.topic not in metadata.topics:
                logger.info(
                    "Topic does not exist. Creating with 3 partitions",
                    extra={"topic": self.config.topic, "partitions": 3},
                )
                topic = NewTopic(
                    topic=self.config.topic,
                    num_partitions=3,
                    replication_factor=1,
                )
                fs = admin.create_topics([topic], operation_timeout=5.0)
                for t, f in fs.items():
                    f.result()  # Wait for creation
                logger.info("Topic created successfully", extra={"topic": self.config.topic})
        except Exception as exc:
            logger.warning(
                "Kafka AdminClient topic check encountered warning",
                extra={"error": str(exc)},
            )

        # 2. Instantiate Producer
        kafka_conf = self.config.to_librdkafka_dict()
        logger.info(
            "Initializing librdkafka Producer",
            extra={
                "bootstrap_servers": self.config.bootstrap_servers,
                "topic": self.config.topic,
                "client_id": self.config.client_id,
            },
        )
        self._producer = Producer(kafka_conf)

    def delivery_report(self, err: Any, msg: Any) -> None:
        """Asynchronous callback executed when message delivery succeeds or fails."""
        if err is not None:
            self.total_failed += 1
            logger.error(
                "Kafka message delivery failed",
                extra={
                    "error": str(err),
                    "topic": msg.topic() if msg else self.config.topic,
                },
            )
        else:
            self.total_delivered += 1
            if self.total_delivered % 500 == 0:
                logger.info(
                    "Kafka message delivery heartbeat",
                    extra={
                        "topic": msg.topic(),
                        "partition": msg.partition(),
                        "offset": msg.offset(),
                        "total_delivered": self.total_delivered,
                    },
                )

    def generate_legitimate_event(self) -> TransactionEvent:
        """Produce a normal, everyday consumer transaction event."""
        user = random.choice(self.user_pool)
        category = random.choice(LEGIT_CATEGORIES)
        merchant = random.choice(LEGIT_MERCHANTS_MAP[category])
        amount = round(random.lognormvariate(3.4, 0.75), 2)
        amount = max(2.50, min(amount, 350.00))

        return TransactionEvent(
            transaction_id=f"tx_{uuid4().hex}",
            user_id=user["user_id"],
            account_id=user["account_id"],
            amount=amount,
            currency="USD",
            merchant_category=category,
            merchant_name=merchant,
            location_country=user["country"],
            location_city=user["city"],
            location_lat=user["lat"],
            location_lon=user["lon"],
            device_id=f"dev_{user['user_id'].hex[:8]}",
            ip_address=f"192.168.1.{random.randint(10, 250)}",
            timestamp=datetime.now(UTC),
            is_foreign_transaction=False,
            is_new_device=False,
        )

    def produce_event(self, event: TransactionEvent) -> None:
        """Serialize event to Kafka JSON and publish with partition key = user_id."""
        self.rate_limiter.acquire(1.0)
        self.total_sent += 1

        # Enforce key invariance: all events for user_id route to the exact same partition
        key_bytes = str(event.user_id).encode("utf-8")
        val_bytes = json.dumps(event.to_kafka_dict()).encode("utf-8")

        if self.config.dry_run or self._producer is None:
            # Simulation / Dry-Run mode
            self.total_delivered += 1
            if self.total_sent % 50 == 0 or self.total_sent <= 5:
                logger.info(
                    "Simulated event emission (dry-run)",
                    extra={
                        "transaction_id": event.transaction_id,
                        "user_id": str(event.user_id),
                        "amount": event.amount,
                        "category": event.merchant_category,
                        "total_sent": self.total_sent,
                    },
                )
            return

        # Asynchronous publication into librdkafka outbox
        self._producer.produce(
            topic=self.config.topic,
            key=key_bytes,
            value=val_bytes,
            on_delivery=self.delivery_report,
        )
        # Non-blocking poll to serve delivery callbacks
        self._producer.poll(0)

    def run(self) -> None:
        """Start the continuous streaming loop."""
        logger.info(
            "Starting synthetic transaction stream",
            extra={
                "target_tps": self.config.tps,
                "anomaly_rate": self.config.anomaly_rate,
                "max_events": self.config.max_events,
                "dry_run": self.config.dry_run,
            },
        )

        start_time = time.monotonic()
        try:
            while not self.stop_requested:
                if self.config.max_events and self.total_sent >= self.config.max_events:
                    logger.info(
                        "Max events reached. Gracefully stopping stream",
                        extra={"total_sent": self.total_sent},
                    )
                    break

                # Determine if anomaly or legitimate event
                is_anomaly = random.random() < self.config.anomaly_rate
                if is_anomaly:
                    victim = random.choice(self.user_pool)
                    anomaly_events = AnomalyGenerator.generate_random_anomaly(
                        user_id=victim["user_id"],
                        account_id=victim["account_id"],
                    )
                    for anom_event in anomaly_events:
                        if self.stop_requested:
                            break
                        self.produce_event(anom_event)
                else:
                    event = self.generate_legitimate_event()
                    self.produce_event(event)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Shutting down producer.")
        finally:
            self.shutdown()
            elapsed = max(0.001, time.monotonic() - start_time)
            effective_tps = round(self.total_sent / elapsed, 2)
            logger.info(
                "Streaming run finalized",
                extra={
                    "total_sent": self.total_sent,
                    "total_delivered": self.total_delivered,
                    "total_failed": self.total_failed,
                    "elapsed_sec": round(elapsed, 2),
                    "effective_tps": effective_tps,
                },
            )

    def shutdown(self) -> None:
        """Flush in-flight buffer and release socket resources."""
        self.stop_requested = True
        if self._producer is not None:
            logger.info("Flushing pending Kafka messages (timeout=10.0s)...")
            self._producer.flush(timeout=10.0)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build command line argument parser for synthetic producer."""
    parser = argparse.ArgumentParser(
        description="High-Throughput Synthetic Kafka Transaction Producer"
    )
    parser.add_argument(
        "--tps",
        type=float,
        default=50.0,
        help="Target transactions-per-second rate limit (default: 50.0)",
    )
    parser.add_argument(
        "--anomaly-rate",
        type=float,
        default=0.02,
        help="Fraction of transactions that inject fraud anomalies (default: 0.02)",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Total transactions to emit before stopping (default: continuous)",
    )
    parser.add_argument(
        "--bootstrap-servers",
        type=str,
        default=settings.KAFKA_BOOTSTRAP_SERVERS,
        help=f"Kafka bootstrap servers (default: {settings.KAFKA_BOOTSTRAP_SERVERS})",
    )
    parser.add_argument(
        "--topic",
        type=str,
        default=settings.KAFKA_TOPIC_TRANSACTIONS,
        help=f"Kafka topic to publish into (default: {settings.KAFKA_TOPIC_TRANSACTIONS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate transactions and log them without publishing to Kafka",
    )
    return parser


def main() -> None:
    """CLI application entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args()

    config = ProducerConfig(
        bootstrap_servers=args.bootstrap_servers,
        topic=args.topic,
        tps=args.tps,
        anomaly_rate=args.anomaly_rate,
        max_events=args.max_events,
        dry_run=args.dry_run,
    )

    producer = TransactionProducer(config=config)

    # Attach signal handlers for graceful shutdown
    def handle_signal(sig: int, frame: Any) -> None:
        logger.info(f"Signal {sig} received. Requesting producer halt...")
        producer.stop_requested = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    producer.run()


if __name__ == "__main__":
    main()
