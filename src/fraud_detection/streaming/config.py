"""Kafka Producer configuration and tuning parameters."""

from dataclasses import dataclass
from typing import Any

from fraud_detection.core.config import settings


@dataclass
class ProducerConfig:
    """Configuration container for synthetic Kafka transaction producer."""

    bootstrap_servers: str = settings.KAFKA_BOOTSTRAP_SERVERS
    topic: str = settings.KAFKA_TOPIC_TRANSACTIONS
    client_id: str = settings.KAFKA_PRODUCER_CLIENT_ID
    acks: str = settings.KAFKA_PRODUCER_ACKS
    linger_ms: int = settings.KAFKA_PRODUCER_LINGER_MS
    batch_num_messages: int = settings.KAFKA_PRODUCER_BATCH_NUM_MESSAGES
    compression_type: str = settings.KAFKA_PRODUCER_COMPRESSION_TYPE
    queue_buffering_max_messages: int = settings.KAFKA_PRODUCER_QUEUE_MAX_MESSAGES
    queue_buffering_max_kbytes: int = settings.KAFKA_PRODUCER_QUEUE_MAX_KBYTES

    # Runtime streaming knobs
    tps: float = 50.0
    anomaly_rate: float = 0.02
    max_events: int | None = None
    dry_run: bool = False

    def to_librdkafka_dict(self) -> dict[str, Any]:
        """Convert settings to librdkafka C-client configuration dictionary."""
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "client.id": self.client_id,
            "acks": self.acks,
            "linger.ms": self.linger_ms,
            "batch.num.messages": self.batch_num_messages,
            "compression.type": self.compression_type,
            "queue.buffering.max.messages": self.queue_buffering_max_messages,
            "queue.buffering.max.kbytes": self.queue_buffering_max_kbytes,
        }


__all__ = ["ProducerConfig"]
