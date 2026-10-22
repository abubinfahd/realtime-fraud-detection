"""Real-time Kafka Fraud Inference Consumer Worker.

Features:
- Consumes raw transaction events from Kafka topic 'transactions' under consumer group 'fraud-inference-engine'.
- Validates schemas with Pydantic V2 and routes corrupt messages to DLQ.
- Queries and updates real-time velocity features in Redis 7 Feature Store (< 1 ms).
- Evaluates deterministic compliance & security rules (Impossible Travel, Velocity Bursts, Sanctions, Nocturnal ATO).
- Executes local hybrid ML model (LightGBM + Fast Isolation Forest) in < 3 ms.
- Emits decisions (APPROVED, FLAGGED, REJECTED) and publishes high-risk alerts to Redis Pub/Sub.
- Manual offset commits to guarantee at-least-once processing.
- Clean graceful shutdown on SIGINT/SIGTERM.
"""

import argparse
import asyncio
import json
import random
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.ml.inference import InferenceEngine
from fraud_detection.rules.rule_engine import RuleEngine
from fraud_detection.schemas.alert import AlertSignals, FraudAlert, VelocityContext
from fraud_detection.schemas.transaction import TransactionEvent
from fraud_detection.storage.redis_feature_store import RedisFeatureStore

logger = get_logger("fraud_detection.streaming.consumer")


class FraudConsumer:
    """Core real-time inference worker consuming from Kafka."""

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        consumer_group: str | None = None,
        topic: str | None = None,
        dlq_topic: str | None = None,
        auto_offset_reset: str = "latest",
        mock_mode: bool = False,
        inference_engine: InferenceEngine | None = None,
        rule_engine: RuleEngine | None = None,
        redis_store: RedisFeatureStore | None = None,
        on_decision: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS
        self.consumer_group = consumer_group or settings.KAFKA_CONSUMER_GROUP
        self.topic = topic or settings.KAFKA_TOPIC_TRANSACTIONS
        self.dlq_topic = dlq_topic or settings.KAFKA_TOPIC_DLQ
        self.auto_offset_reset = auto_offset_reset
        self.mock_mode = mock_mode

        # Processing subcomponents
        self.inference_engine = inference_engine or InferenceEngine()
        self.rule_engine = rule_engine or RuleEngine()
        self.redis_store = redis_store or RedisFeatureStore(mock_mode=mock_mode)
        self.on_decision = on_decision

        # Lifecycle state
        self.running = False
        self._consumer: Any = None
        self._dlq_producer: Any = None

        # Statistics
        self.processed_count = 0
        self.approved_count = 0
        self.flagged_count = 0
        self.rejected_count = 0
        self.dlq_count = 0
        self.latencies_ms: list[float] = []
        self.published_alerts: list[dict[str, Any]] = []

    def _init_kafka_consumer(self) -> None:
        """Initialize confluent-kafka Consumer and DLQ Producer."""
        if self.mock_mode:
            logger.info("FraudConsumer running in MOCK mode (skipping live Kafka connection).")
            return

        try:
            from confluent_kafka import Consumer, Producer

            conf = {
                "bootstrap.servers": self.bootstrap_servers,
                "group.id": self.consumer_group,
                "auto.offset.reset": self.auto_offset_reset,
                "enable.auto.commit": False,  # Manual at-least-once commits
                "session.timeout.ms": 45000,
                "max.poll.interval.ms": 300000,
            }
            self._consumer = Consumer(conf)
            self._consumer.subscribe([self.topic])

            # DLQ Producer for corrupt poison pills
            dlq_conf = {
                "bootstrap.servers": self.bootstrap_servers,
                "client.id": f"{self.consumer_group}-dlq",
                "acks": "1",
            }
            self._dlq_producer = Producer(dlq_conf)
            logger.info(
                "Connected to Kafka broker",
                extra={
                    "bootstrap_servers": self.bootstrap_servers,
                    "topic": self.topic,
                    "group": self.consumer_group,
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to initialize Kafka consumer. Falling back to mock mode.",
                extra={"error": str(exc)},
            )
            self.mock_mode = True

    async def _send_to_dlq(
        self,
        raw_payload: str | bytes,
        error_msg: str,
        topic: str | None = None,
        partition: int | None = None,
        offset: int | None = None,
    ) -> None:
        """Route unparseable or schema-violating poison pills to the DLQ topic."""
        self.dlq_count += 1
        dlq_record = {
            "error": error_msg,
            "source_topic": topic or self.topic,
            "source_partition": partition,
            "source_offset": offset,
            "timestamp": datetime.now(UTC).isoformat(),
            "raw_payload": (
                raw_payload.decode("utf-8", errors="replace")
                if isinstance(raw_payload, bytes)
                else str(raw_payload)
            ),
        }
        logger.warning(
            "Poison pill routed to DLQ",
            extra={"error": error_msg, "dlq_topic": self.dlq_topic},
        )

        if self._dlq_producer and not self.mock_mode:
            try:
                self._dlq_producer.produce(
                    topic=self.dlq_topic,
                    value=json.dumps(dlq_record).encode("utf-8"),
                )
                self._dlq_producer.poll(0)
            except Exception as exc:
                logger.error("Failed to publish message to DLQ topic", extra={"error": str(exc)})

    async def _publish_alert_pubsub(
        self,
        decision: dict[str, Any],
        velocity: dict[str, Any],
    ) -> None:
        """Publish high-risk fraud alerts (FLAGGED or REJECTED) to Redis Pub/Sub."""
        try:
            user_uuid = (
                UUID(decision["user_id"])
                if isinstance(decision["user_id"], str)
                else decision["user_id"]
            )
            alert = FraudAlert(
                event_type="FRAUD_ALERT",
                transaction_id=decision["transaction_id"],
                user_id=user_uuid,
                amount=decision["amount"],
                currency=decision.get("currency", "USD"),
                status=decision["status"],
                risk_score=decision["risk_score"],
                merchant_name=decision["merchant_name"],
                merchant_category=decision["merchant_category"],
                signals=AlertSignals(
                    lgbm_fraud_prob=decision["fraud_probability"],
                    anomaly_score=decision["anomaly_score"],
                    rule_violations=decision["rule_violations"],
                ),
                velocity_context=VelocityContext(
                    tx_count_1m=int(velocity.get("tx_count_1m", 1)),
                    tx_count_10m=int(velocity.get("tx_count_10m", 1)),
                    tx_sum_10m=float(velocity.get("tx_sum_10m", decision["amount"])),
                    amount_to_avg_ratio=float(velocity.get("amount_to_avg_ratio", 1.0)),
                ),
                inference_latency_ms=decision["latency_ms"],
            )

            alert_dict = alert.model_dump(mode="json")
            self.published_alerts.append(alert_dict)

            if self.redis_store._client is not None and not self.redis_store.mock_mode:
                await self.redis_store._client.publish(
                    settings.REDIS_ALERTS_CHANNEL,
                    json.dumps(alert_dict),
                )
        except Exception as exc:
            logger.warning("Error broadcasting alert to Redis Pub/Sub", extra={"error": str(exc)})

    async def process_raw_message(
        self,
        raw_payload: str | bytes,
        topic: str | None = None,
        partition: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any] | None:
        """Process a single Kafka payload end-to-end through validation, Redis, Rules, and ML."""
        t_start = time.perf_counter()

        # 1. Validation & Schema Parsing
        try:
            if isinstance(raw_payload, bytes):
                payload_str = raw_payload.decode("utf-8")
            else:
                payload_str = str(raw_payload)

            tx_event = TransactionEvent.model_validate_json(payload_str)
        except (ValidationError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            await self._send_to_dlq(
                raw_payload=raw_payload,
                error_msg=str(exc),
                topic=topic,
                partition=partition,
                offset=offset,
            )
            return None

        tx_dict = tx_event.model_dump(mode="json")
        user_id = tx_event.user_id

        # 2. Redis Feature Store Retrieval & Velocity Update
        velocity = await self.redis_store.update_and_get_velocity_features(
            user_id=user_id,
            transaction_id=tx_event.transaction_id,
            amount=tx_event.amount,
            timestamp=tx_event.timestamp,
        )

        # 3. Retrieve Geolocation & Evaluate Deterministic Rules
        last_loc = await self.redis_store.get_last_location(user_id)

        # Update last location if current transaction contains coordinates
        if tx_event.location_lat is not None and tx_event.location_lon is not None:
            await self.redis_store.set_last_location(
                user_id=user_id,
                lat=tx_event.location_lat,
                lon=tx_event.location_lon,
                timestamp=tx_event.timestamp,
                country=tx_event.location_country,
                city=tx_event.location_city,
            )

        rule_result = self.rule_engine.evaluate(
            transaction=tx_dict,
            velocity=velocity,
            last_location=last_loc,
        )

        # 4. Hybrid ML Inference & Decision Synthesis
        decision = self.inference_engine.score_transaction(
            transaction=tx_dict,
            velocity=velocity,
            rule_result=rule_result,
        )

        # Total in-process consumer latency
        total_latency_ms = (time.perf_counter() - t_start) * 1000.0
        decision["total_latency_ms"] = round(total_latency_ms, 3)

        # 5. Alert Broadcasting for High-Risk Events
        if decision["status"] in ("FLAGGED", "REJECTED"):
            await self._publish_alert_pubsub(decision, velocity)

        # 6. Execute Registered Callback (e.g. for Stage 7 DB batch buffer)
        if self.on_decision:
            try:
                res = self.on_decision(decision)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                logger.error("Error in on_decision callback", extra={"error": str(exc)})

        # Record metrics
        self.processed_count += 1
        if decision["status"] == "APPROVED":
            self.approved_count += 1
        elif decision["status"] == "FLAGGED":
            self.flagged_count += 1
        else:
            self.rejected_count += 1

        self.latencies_ms.append(total_latency_ms)
        return decision

    async def start(
        self,
        max_messages: int | None = None,
        batch_size: int = 100,
    ) -> None:
        """Start the async consumption loop."""
        self.running = True
        self._init_kafka_consumer()
        await self.redis_store.initialize()

        logger.info(
            "FraudConsumer worker started",
            extra={"max_messages": max_messages, "topic": self.topic},
        )
        print(f"[*] FraudConsumer started on topic '{self.topic}' [Group: {self.consumer_group}]")
        print("[*] Press Ctrl+C to initiate graceful shutdown.")

        loop_start_time = time.time()

        try:
            while self.running:
                if max_messages and self.processed_count >= max_messages:
                    logger.info("Reached target max_messages limit. Stopping.")
                    break

                if self.mock_mode or self._consumer is None:
                    # In mock mode, synthesize realistic transactions (with 10% anomalies)
                    from fraud_detection.streaming.anomalies import AnomalyGenerator
                    from fraud_detection.streaming.producer import TransactionProducer

                    if not hasattr(self, "_mock_producer"):
                        self._mock_producer = TransactionProducer()

                    if random.random() < 0.10:
                        user = random.choice(self._mock_producer.user_pool)
                        anomalies = AnomalyGenerator.generate_random_anomaly(
                            user_id=user["user_id"],
                            account_id=user["account_id"],
                        )
                        for ev in anomalies:
                            await self.process_raw_message(ev.model_dump_json())
                            if max_messages and self.processed_count >= max_messages:
                                break
                    else:
                        ev = self._mock_producer.generate_legitimate_event()
                        await self.process_raw_message(ev.model_dump_json())

                    await asyncio.sleep(0.01)

                    report_interval = 10 if (max_messages and max_messages <= 100) else 100
                    if self.processed_count % report_interval == 0 and self.processed_count > 0:
                        elapsed = max(time.time() - loop_start_time, 0.001)
                        tps = self.processed_count / elapsed
                        mean_lat = (
                            sum(self.latencies_ms[-report_interval:])
                            / len(self.latencies_ms[-report_interval:])
                            if self.latencies_ms
                            else 0.0
                        )
                        print(
                            f"[*] Processed: {self.processed_count:,} | TPS: {tps:.1f} | "
                            f"Avg Latency: {mean_lat:.2f} ms | "
                            f"APPROVED: {self.approved_count} | FLAGGED: {self.flagged_count} | "
                            f"REJECTED: {self.rejected_count} | DLQ: {self.dlq_count}"
                        )
                    continue

                # Poll Kafka batch
                msg = self._consumer.poll(timeout=0.1)
                if msg is None:
                    await asyncio.sleep(0.005)
                    continue

                if msg.error():
                    from confluent_kafka import KafkaError

                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        logger.error("Kafka consumer error", extra={"error": str(msg.error())})
                        continue

                # Process transaction
                await self.process_raw_message(
                    raw_payload=msg.value(),
                    topic=msg.topic(),
                    partition=msg.partition(),
                    offset=msg.offset(),
                )

                # Manual at-least-once commit
                try:
                    self._consumer.commit(msg, asynchronous=True)
                except Exception as exc:
                    logger.warning("Failed to commit Kafka offset", extra={"error": str(exc)})

                # Periodic terminal progress report every 100 messages
                report_interval = 10 if (max_messages and max_messages <= 100) else 100
                if self.processed_count % report_interval == 0 and self.processed_count > 0:
                    elapsed = max(time.time() - loop_start_time, 0.001)
                    tps = self.processed_count / elapsed
                    mean_lat = (
                        sum(self.latencies_ms[-report_interval:])
                        / len(self.latencies_ms[-report_interval:])
                        if self.latencies_ms
                        else 0.0
                    )
                    print(
                        f"[*] Processed: {self.processed_count:,} | TPS: {tps:.1f} | "
                        f"Avg Latency: {mean_lat:.2f} ms | "
                        f"APPROVED: {self.approved_count} | FLAGGED: {self.flagged_count} | "
                        f"REJECTED: {self.rejected_count} | DLQ: {self.dlq_count}"
                    )

        except asyncio.CancelledError:
            logger.info("Consumer loop cancelled.")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Gracefully release Kafka consumer, flush DLQ producer, and close Redis."""
        if not self.running and self._consumer is None:
            return

        self.running = False
        print("\n[*] Gracefully stopping FraudConsumer worker...")

        # Commit final offsets and close consumer
        if self._consumer is not None and not self.mock_mode:
            try:
                self._consumer.commit(asynchronous=False)
            except Exception:
                pass
            try:
                self._consumer.close()
            except Exception:
                pass
            self._consumer = None

        # Flush DLQ producer
        if self._dlq_producer is not None:
            try:
                self._dlq_producer.flush(timeout=3.0)
            except Exception:
                pass
            self._dlq_producer = None

        # Close Redis connection pool
        await self.redis_store.close()

        print("=" * 80)
        print("FraudConsumer Execution Summary")
        print("=" * 80)
        print(f"Total Transactions Processed: {self.processed_count:,}")
        print(f"  - APPROVED:                 {self.approved_count:,}")
        print(f"  - FLAGGED:                  {self.flagged_count:,}")
        print(f"  - REJECTED:                 {self.rejected_count:,}")
        print(f"  - DLQ (Corrupt):            {self.dlq_count:,}")
        if self.latencies_ms:
            import numpy as np

            print(f"Latency Mean:                 {np.mean(self.latencies_ms):.2f} ms")
            print(f"Latency P95:                  {np.percentile(self.latencies_ms, 95):.2f} ms")
            print(f"Latency P99:                  {np.percentile(self.latencies_ms, 99):.2f} ms")
        print("=" * 80)
        logger.info("FraudConsumer stopped cleanly.")


def parse_args() -> argparse.Namespace:
    """Parse consumer command-line arguments."""
    parser = argparse.ArgumentParser(description="Real-Time Kafka Fraud Detection Consumer Worker")
    parser.add_argument(
        "--bootstrap-servers",
        type=str,
        default=settings.KAFKA_BOOTSTRAP_SERVERS,
        help="Kafka bootstrap server connection string (default: localhost:9092)",
    )
    parser.add_argument(
        "--topic",
        type=str,
        default=settings.KAFKA_TOPIC_TRANSACTIONS,
        help="Source Kafka topic (default: transactions)",
    )
    parser.add_argument(
        "--group-id",
        type=str,
        default=settings.KAFKA_CONSUMER_GROUP,
        help="Kafka consumer group ID (default: fraud-inference-engine)",
    )
    parser.add_argument(
        "--auto-offset-reset",
        type=str,
        default="latest",
        choices=["latest", "earliest"],
        help="Auto offset reset policy (default: latest)",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="Stop consumer after processing N messages",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in mock mode without live Kafka broker",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint for fraud-consumer."""
    args = parse_args()

    consumer = FraudConsumer(
        bootstrap_servers=args.bootstrap_servers,
        topic=args.topic,
        consumer_group=args.group_id,
        auto_offset_reset=args.auto_offset_reset,
        mock_mode=args.mock,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _signal_handler() -> None:
        consumer.running = False

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, RuntimeError):
            # Windows signal handlers compatibility
            signal.signal(sig, lambda *_: _signal_handler())

    try:
        loop.run_until_complete(consumer.start(max_messages=args.max_messages))
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(consumer.stop())
        loop.close()


if __name__ == "__main__":
    main()
