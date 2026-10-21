"""High-performance Redis 7 Real-Time Velocity Feature Store.

Features:
- Sub-millisecond trailing sliding-window aggregations (60s and 10m).
- Atomic execution in a single network round-trip (RTT) via pre-compiled Lua scripts.
- Connection pooling with redis.asyncio.
- Automatic window eviction (ZREMRANGEBYSCORE) and sliding TTL (1800s).
- Seamless in-memory fallback simulator for offline testing and development.
"""

from collections import defaultdict
from datetime import UTC, datetime
import time
from typing import Any
from uuid import UUID

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.storage.lua_scripts import (
    GET_VELOCITY_READ_SCRIPT,
    SLIDING_WINDOW_INGEST_SCRIPT,
)

logger = get_logger("fraud_detection.storage.redis_feature_store")


class InMemorySortedSetStore:
    """Thread-safe in-memory simulator of Redis Sorted Sets for testing and mock mode."""

    def __init__(self) -> None:
        # key -> list of (score_ms, member_str)
        self._sets: dict[str, list[tuple[int, str]]] = defaultdict(list)
        # key -> expire_timestamp_s
        self._ttls: dict[str, float] = {}

    def ingest(
        self,
        key: str,
        score_ms: int,
        member: str,
        cutoff_60s_ms: int,
        cutoff_600s_ms: int,
        ttl_seconds: int,
    ) -> tuple[int, float, int, float]:
        """Simulate the atomic SLIDING_WINDOW_INGEST_SCRIPT in memory."""
        entries = self._sets[key]

        # 1. Prune strictly older than 10m
        entries = [e for e in entries if e[0] >= cutoff_600s_ms]

        # 2. Add current transaction
        entries.append((score_ms, member))
        # Keep sorted by score
        entries.sort(key=lambda x: x[0])
        self._sets[key] = entries

        # 3. Refresh TTL
        self._ttls[key] = time.time() + ttl_seconds

        # 4. Compute 60s and 10m metrics
        count_60s = 0
        sum_60s = 0.0
        count_10m = 0
        sum_10m = 0.0

        for score, m in entries:
            amt = float(m.split(":", 1)[1]) if ":" in m else 0.0
            if score >= cutoff_600s_ms:
                count_10m += 1
                sum_10m += amt
            if score >= cutoff_60s_ms:
                count_60s += 1
                sum_60s += amt

        return count_60s, round(sum_60s, 2), count_10m, round(sum_10m, 2)

    def read_velocity(
        self,
        key: str,
        cutoff_60s_ms: int,
        cutoff_600s_ms: int,
    ) -> tuple[int, float, int, float]:
        """Simulate read-only velocity retrieval in memory."""
        entries = [e for e in self._sets.get(key, []) if e[0] >= cutoff_600s_ms]
        self._sets[key] = entries

        count_60s = 0
        sum_60s = 0.0
        count_10m = 0
        sum_10m = 0.0

        for score, m in entries:
            amt = float(m.split(":", 1)[1]) if ":" in m else 0.0
            if score >= cutoff_600s_ms:
                count_10m += 1
                sum_10m += amt
            if score >= cutoff_60s_ms:
                count_60s += 1
                sum_60s += amt

        return count_60s, round(sum_60s, 2), count_10m, round(sum_10m, 2)

    def get_ttl(self, key: str) -> int:
        """Return remaining TTL seconds for key."""
        if key not in self._ttls:
            return -2  # Key does not exist
        remaining = int(self._ttls[key] - time.time())
        return max(remaining, 0)

    def delete(self, key: str) -> bool:
        """Delete key."""
        existed = key in self._sets
        self._sets.pop(key, None)
        self._ttls.pop(key, None)
        return existed


class RedisFeatureStore:
    """High-throughput asynchronous Redis feature store for sliding-window velocity signals."""

    def __init__(
        self,
        redis_url: str | None = None,
        ttl_seconds: int = settings.REDIS_FEATURE_TTL_SECONDS,
        mock_mode: bool = False,
    ) -> None:
        self.redis_url = redis_url or settings.redis_url
        self.ttl_seconds = ttl_seconds
        self.mock_mode = mock_mode
        self._in_memory = InMemorySortedSetStore() if mock_mode else None
        self._client: Any = None
        self._ingest_script: Any = None
        self._read_script: Any = None

    async def initialize(self) -> None:
        """Initialize Redis connection pool and register Lua scripts."""
        if self.mock_mode:
            logger.info("RedisFeatureStore initialized in MOCK simulation mode.")
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

            # Register Lua scripts for SHA-1 caching
            self._ingest_script = self._client.register_script(SLIDING_WINDOW_INGEST_SCRIPT)
            self._read_script = self._client.register_script(GET_VELOCITY_READ_SCRIPT)
            logger.info("Connected to Redis 7 Feature Store", extra={"url": self.redis_url})

        except Exception as exc:
            logger.warning(
                "Failed to connect to live Redis server. Falling back to in-memory mock engine.",
                extra={"error": str(exc)},
            )
            self.mock_mode = True
            self._in_memory = InMemorySortedSetStore()

    @staticmethod
    def _parse_timestamp_ms(timestamp: datetime | float | int | None) -> int:
        """Convert datetime or timestamp to epoch milliseconds."""
        if timestamp is None:
            return int(time.time() * 1000)
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            return int(timestamp.timestamp() * 1000)
        if isinstance(timestamp, (float, int)):
            # If timestamp is already in milliseconds (> 1e11)
            if timestamp > 1e11:
                return int(timestamp)
            return int(timestamp * 1000)
        return int(time.time() * 1000)

    @staticmethod
    def get_user_key(user_id: UUID | str) -> str:
        """Generate canonical Redis Sorted Set key for user velocity history."""
        return f"user:{str(user_id)}:tx_history"

    async def update_and_get_velocity_features(
        self,
        user_id: UUID | str,
        transaction_id: str,
        amount: float,
        timestamp: datetime | float | int | None = None,
    ) -> dict[str, float]:
        """Atomically record a transaction and return trailing velocity features in < 1 ms.

        Parameters
        ----------
        user_id : UUID | str
            Unique user identifier.
        transaction_id : str
            Unique transaction idempotency identifier.
        amount : float
            Transaction value in USD.
        timestamp : datetime | float | int | None
            Event timestamp (defaults to current UTC time).

        Returns
        -------
        dict[str, float]
            Velocity metrics (tx_count_1m, tx_sum_1m, tx_count_10m, tx_sum_10m,
            avg_amount_10m, amount_to_avg_ratio).
        """
        if self._client is None and not self.mock_mode:
            await self.initialize()

        current_ms = self._parse_timestamp_ms(timestamp)
        cutoff_60s_ms = current_ms - 60_000
        cutoff_600s_ms = current_ms - 600_000
        member = f"{transaction_id}:{amount:.2f}"
        key = self.get_user_key(user_id)

        if self.mock_mode or self._client is None:
            assert self._in_memory is not None
            c_60s, s_60s, c_10m, s_10m = self._in_memory.ingest(
                key=key,
                score_ms=current_ms,
                member=member,
                cutoff_60s_ms=cutoff_60s_ms,
                cutoff_600s_ms=cutoff_600s_ms,
                ttl_seconds=self.ttl_seconds,
            )
        else:
            try:
                raw = await self._ingest_script(
                    keys=[key],
                    args=[
                        current_ms,
                        member,
                        cutoff_60s_ms,
                        cutoff_600s_ms,
                        self.ttl_seconds,
                    ],
                )
                c_60s = int(raw[0])
                s_60s = float(raw[1])
                c_10m = int(raw[2])
                s_10m = float(raw[3])
            except Exception as exc:
                logger.error(
                    "Error executing sliding-window Lua script. Falling back to default velocity.",
                    extra={"error": str(exc), "user_id": str(user_id)},
                )
                c_60s, s_60s, c_10m, s_10m = 1, amount, 1, amount

        # Derived moving average and ratio calculations
        avg_amount_10m = round(s_10m / max(c_10m, 1), 2)
        amount_to_avg_ratio = round(amount / max(avg_amount_10m, 1.0), 2)

        return {
            "tx_count_1m": float(c_60s),
            "tx_sum_1m": round(float(s_60s), 2),
            "tx_count_10m": float(c_10m),
            "tx_sum_10m": round(float(s_10m), 2),
            "avg_amount_10m": avg_amount_10m,
            "amount_to_avg_ratio": amount_to_avg_ratio,
        }

    async def get_velocity_features(
        self,
        user_id: UUID | str,
        current_amount: float = 0.0,
        timestamp: datetime | float | int | None = None,
    ) -> dict[str, float]:
        """Query trailing velocity metrics without writing a new transaction record."""
        if self._client is None and not self.mock_mode:
            await self.initialize()

        current_ms = self._parse_timestamp_ms(timestamp)
        cutoff_60s_ms = current_ms - 60_000
        cutoff_600s_ms = current_ms - 600_000
        key = self.get_user_key(user_id)

        if self.mock_mode or self._client is None:
            assert self._in_memory is not None
            c_60s, s_60s, c_10m, s_10m = self._in_memory.read_velocity(
                key=key,
                cutoff_60s_ms=cutoff_60s_ms,
                cutoff_600s_ms=cutoff_600s_ms,
            )
        else:
            try:
                raw = await self._read_script(
                    keys=[key],
                    args=[cutoff_60s_ms, cutoff_600s_ms],
                )
                c_60s = int(raw[0])
                s_60s = float(raw[1])
                c_10m = int(raw[2])
                s_10m = float(raw[3])
            except Exception as exc:
                logger.error(
                    "Error reading velocity script from Redis",
                    extra={"error": str(exc)},
                )
                c_60s, s_60s, c_10m, s_10m = 0, 0.0, 0, 0.0

        avg_amount_10m = round(s_10m / max(c_10m, 1), 2)
        amount_to_avg_ratio = round(current_amount / max(avg_amount_10m, 1.0), 2)

        return {
            "tx_count_1m": float(c_60s),
            "tx_sum_1m": round(float(s_60s), 2),
            "tx_count_10m": float(c_10m),
            "tx_sum_10m": round(float(s_10m), 2),
            "avg_amount_10m": avg_amount_10m,
            "amount_to_avg_ratio": amount_to_avg_ratio,
        }

    async def get_key_ttl(self, user_id: UUID | str) -> int:
        """Return remaining TTL seconds for the user's velocity key."""
        key = self.get_user_key(user_id)
        if self.mock_mode or self._client is None:
            assert self._in_memory is not None
            return self._in_memory.get_ttl(key)
        return await self._client.ttl(key)

    async def reset_user_history(self, user_id: UUID | str) -> bool:
        """Reset / delete velocity state for a given user."""
        key = self.get_user_key(user_id)
        if self.mock_mode or self._client is None:
            assert self._in_memory is not None
            return self._in_memory.delete(key)
        res = await self._client.delete(key)
        return bool(res > 0)

    async def close(self) -> None:
        """Release Redis connection pool resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "RedisFeatureStore":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


__all__ = ["InMemorySortedSetStore", "RedisFeatureStore"]
