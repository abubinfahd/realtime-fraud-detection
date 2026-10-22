"""Unit tests for Stage 5: Redis Real-Time Velocity Feature Store and Lua scripts."""

import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest

from fraud_detection.ml.features import FEATURE_NAMES, extract_features
from fraud_detection.storage.benchmark import run_benchmark
from fraud_detection.storage.lua_scripts import (
    GET_VELOCITY_READ_SCRIPT,
    SLIDING_WINDOW_INGEST_SCRIPT,
)
from fraud_detection.storage.redis_feature_store import (
    InMemorySortedSetStore,
    RedisFeatureStore,
)


class TestLuaScripts:
    """Test suite validating Lua script definitions."""

    def test_scripts_are_non_empty_strings(self) -> None:
        """Verify Lua script strings are populated with valid syntax elements."""
        assert "ZREMRANGEBYSCORE" in SLIDING_WINDOW_INGEST_SCRIPT
        assert "ZADD" in SLIDING_WINDOW_INGEST_SCRIPT
        assert "ZRANGEBYSCORE" in SLIDING_WINDOW_INGEST_SCRIPT
        assert "EXPIRE" in SLIDING_WINDOW_INGEST_SCRIPT

        assert "ZREMRANGEBYSCORE" in GET_VELOCITY_READ_SCRIPT
        assert "ZRANGEBYSCORE" in GET_VELOCITY_READ_SCRIPT


class TestInMemorySortedSetStore:
    """Test suite for the thread-safe in-memory sorted set simulator."""

    def test_single_event_ingestion(self) -> None:
        """Verify single transaction creates proper window counts and sums."""
        store = InMemorySortedSetStore()
        now_ms = int(time.time() * 1000)

        c60, s60, c10, s10 = store.ingest(
            key="user:test:tx_history",
            score_ms=now_ms,
            member="tx_1:50.00",
            cutoff_60s_ms=now_ms - 60_000,
            cutoff_600s_ms=now_ms - 600_000,
            ttl_seconds=1800,
        )

        assert c60 == 1
        assert s60 == 50.00
        assert c10 == 1
        assert s10 == 50.00

    def test_window_eviction_and_partitioning(self) -> None:
        """Verify items older than 600s are evicted, and 60s items are filtered."""
        store = InMemorySortedSetStore()
        now_ms = 1_000_000_000

        # Event 1: 700s ago (stale, must be evicted)
        store.ingest(
            key="user:test:tx_history",
            score_ms=now_ms - 700_000,
            member="tx_old:100.00",
            cutoff_60s_ms=now_ms - 60_000,
            cutoff_600s_ms=now_ms - 600_000,
            ttl_seconds=1800,
        )

        # Event 2: 180s ago (within 10m, outside 60s)
        store.ingest(
            key="user:test:tx_history",
            score_ms=now_ms - 180_000,
            member="tx_mid:40.00",
            cutoff_60s_ms=now_ms - 60_000,
            cutoff_600s_ms=now_ms - 600_000,
            ttl_seconds=1800,
        )

        # Event 3: now (within 60s and 10m)
        c60, s60, c10, s10 = store.ingest(
            key="user:test:tx_history",
            score_ms=now_ms,
            member="tx_now:60.00",
            cutoff_60s_ms=now_ms - 60_000,
            cutoff_600s_ms=now_ms - 600_000,
            ttl_seconds=1800,
        )

        # tx_old was evicted, so 10m window has tx_mid + tx_now = 2 items, sum=100.00
        assert c10 == 2
        assert s10 == 100.00

        # 60s window has only tx_now = 1 item, sum=60.00
        assert c60 == 1
        assert s60 == 60.00


class TestRedisFeatureStore:
    """Test suite for RedisFeatureStore async interface."""

    @pytest.mark.asyncio
    async def test_update_and_get_velocity_features(self) -> None:
        """Verify update_and_get_velocity_features returns expected schema and values."""
        user_id = uuid4()
        now = datetime.now(UTC)

        async with RedisFeatureStore(mock_mode=True) as store:
            vel = await store.update_and_get_velocity_features(
                user_id=user_id,
                transaction_id="tx_test_1",
                amount=75.50,
                timestamp=now,
            )

            assert isinstance(vel, dict)
            assert vel["tx_count_1m"] == 1.0
            assert vel["tx_sum_1m"] == 75.50
            assert vel["tx_count_10m"] == 1.0
            assert vel["tx_sum_10m"] == 75.50
            assert vel["avg_amount_10m"] == 75.50
            assert vel["amount_to_avg_ratio"] == 1.00

    @pytest.mark.asyncio
    async def test_user_isolation(self) -> None:
        """Verify transactions from User A do not pollute velocity of User B."""
        user_a = uuid4()
        user_b = uuid4()
        now = datetime.now(UTC)

        async with RedisFeatureStore(mock_mode=True) as store:
            await store.update_and_get_velocity_features(
                user_id=user_a,
                transaction_id="tx_a1",
                amount=50.00,
                timestamp=now,
            )
            await store.update_and_get_velocity_features(
                user_id=user_a,
                transaction_id="tx_a2",
                amount=70.00,
                timestamp=now,
            )

            # User B makes 1 transaction
            vel_b = await store.update_and_get_velocity_features(
                user_id=user_b,
                transaction_id="tx_b1",
                amount=20.00,
                timestamp=now,
            )

            assert vel_b["tx_count_1m"] == 1.0
            assert vel_b["tx_sum_1m"] == 20.00
            assert vel_b["tx_count_10m"] == 1.0
            assert vel_b["tx_sum_10m"] == 20.00

    @pytest.mark.asyncio
    async def test_sliding_window_velocity_accumulation(self) -> None:
        """Verify multiple rapid transactions accumulate in 1m and 10m windows."""
        user_id = uuid4()
        base_time = datetime.now(UTC)

        async with RedisFeatureStore(mock_mode=True) as store:
            # 1. First transaction
            await store.update_and_get_velocity_features(
                user_id=user_id,
                transaction_id="tx_1",
                amount=10.00,
                timestamp=base_time - timedelta(seconds=20),
            )

            # 2. Second transaction 10s later
            await store.update_and_get_velocity_features(
                user_id=user_id,
                transaction_id="tx_2",
                amount=20.00,
                timestamp=base_time - timedelta(seconds=10),
            )

            # 3. Third transaction now
            vel = await store.update_and_get_velocity_features(
                user_id=user_id,
                transaction_id="tx_3",
                amount=30.00,
                timestamp=base_time,
            )

            assert vel["tx_count_1m"] == 3.0
            assert vel["tx_sum_1m"] == 60.00
            assert vel["tx_count_10m"] == 3.0
            assert vel["tx_sum_10m"] == 60.00
            assert vel["avg_amount_10m"] == 20.00  # 60 / 3
            assert vel["amount_to_avg_ratio"] == 1.50  # 30 / 20

    @pytest.mark.asyncio
    async def test_get_key_ttl_and_reset(self) -> None:
        """Verify TTL retrieval and history reset functionality."""
        user_id = uuid4()

        async with RedisFeatureStore(mock_mode=True, ttl_seconds=1800) as store:
            await store.update_and_get_velocity_features(
                user_id=user_id,
                transaction_id="tx_ttl",
                amount=45.00,
            )

            ttl = await store.get_key_ttl(user_id)
            assert 1700 <= ttl <= 1800

            # Reset history
            deleted = await store.reset_user_history(user_id)
            assert deleted is True

            # Key should no longer exist
            ttl_after = await store.get_key_ttl(user_id)
            assert ttl_after <= 0

    @pytest.mark.asyncio
    async def test_extract_features_integration(self, sample_transaction_dict: dict) -> None:
        """Verify velocity dictionary directly feeds into ML feature extractor."""
        user_id = uuid4()
        now = datetime.now(UTC)

        async with RedisFeatureStore(mock_mode=True) as store:
            vel = await store.update_and_get_velocity_features(
                user_id=user_id,
                transaction_id="tx_feat_1",
                amount=150.00,
                timestamp=now,
            )

            vector = extract_features(
                transaction=sample_transaction_dict,
                velocity=vel,
            )

            assert isinstance(vector, np.ndarray)
            assert vector.shape == (len(FEATURE_NAMES),)
            # Check positions:
            # tx_count_1m = index 4
            # tx_count_10m = index 5
            # tx_sum_10m = index 6
            assert vector[4] == 1.0
            assert vector[5] == 1.0
            assert vector[6] == 150.00


class TestBenchmarkExecution:
    """Test suite for the Redis feature store concurrency benchmark."""

    @pytest.mark.asyncio
    async def test_run_benchmark_mock_mode(self) -> None:
        """Verify benchmark completes without error and produces valid statistics."""
        results = await run_benchmark(
            num_ops=200,
            concurrency=10,
            mock_mode=True,
        )

        assert results["total_ops"] == 200.0
        assert results["throughput_ops_sec"] > 500.0
        assert results["p95_latency_ms"] < 1.0
        assert results["p50_latency_ms"] < results["p95_latency_ms"]
