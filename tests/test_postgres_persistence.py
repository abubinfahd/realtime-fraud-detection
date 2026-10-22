"""Unit tests for Stage 7 — PostgreSQL Persistence Layer & Micro-Batching Buffer.

Covers:
- PostgresPool connection lifecycle and fallback simulator.
- TransactionRepository batched inserts, exact monetary precision, and idempotency.
- PersistenceBuffer size-triggered and time-triggered async flushes.
- FraudConsumer end-to-end integration with persistence sink.
"""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from fraud_detection.storage.postgres_pool import (
    InMemoryPostgresConnection,
    PostgresPool,
)
from fraud_detection.storage.transaction_repository import TransactionRepository
from fraud_detection.streaming.consumer import FraudConsumer
from fraud_detection.streaming.persistence_buffer import PersistenceBuffer


@pytest.fixture
def mock_pool() -> PostgresPool:
    """Provide an in-memory mock PostgresPool fixture."""
    return PostgresPool(mock_mode=True)


@pytest.fixture
def repo(mock_pool: PostgresPool) -> TransactionRepository:
    """Provide a TransactionRepository attached to an in-memory mock pool."""
    return TransactionRepository(mock_pool)


@pytest.mark.asyncio
async def test_postgres_pool_lifecycle(mock_pool: PostgresPool) -> None:
    """Test PostgresPool mock mode initialization, acquire, query execution, and closure."""
    await mock_pool.initialize()
    assert mock_pool.mock_mode is True

    async with mock_pool.acquire() as conn:
        assert isinstance(conn, InMemoryPostgresConnection)
        exec_res = await conn.execute("INSERT INTO users VALUES (1, 'test', 'Test')")
        assert exec_res == "INSERT 0 1"

        many_res = await conn.executemany("INSERT INTO users VALUES ($1)", [("a",), ("b",)])
        assert "2" in many_res

        val = await conn.fetchval("SELECT 1")
        assert val is None or val == 1

        async with conn.transaction():
            pass

    await mock_pool.close()


@pytest.mark.asyncio
async def test_repository_save_and_idempotency(repo: TransactionRepository) -> None:
    """Test multi-row batch save, exact monetary precision, and duplicate idempotency."""
    tx_ref = f"tx_test_{uuid4().hex[:8]}"
    u_id = str(uuid4())
    acc_id = str(uuid4())

    decisions = [
        {
            "transaction_id": tx_ref,
            "user_id": u_id,
            "account_id": acc_id,
            "amount": 149.99,
            "currency": "USD",
            "merchant_category": "retail",
            "merchant_name": "Apple Store",
            "location_country": "US",
            "location_lat": 37.7749,
            "location_lon": -122.4194,
            "device_id": "dev_ios_1",
            "ip_address": "192.168.1.50",
            "status": "APPROVED",
            "risk_score": 0.0450,
            "features": {"amount_scaled": 1.25, "velocity_1h_count": 1.0},
            "rule_violations": [],
            "timestamp": "2026-10-22T10:00:00Z",
        }
    ]

    # 1. Initial batch insert
    inserted = await repo.save_transactions_batch(decisions)
    assert inserted == 1

    # 2. Verify stored record fidelity and exact precision
    record = await repo.get_transaction_by_ref(tx_ref)
    assert record is not None
    assert record["transaction_ref"] == tx_ref
    assert record["amount"] == Decimal("149.99")
    assert record["status"] == "APPROVED"
    assert record["risk_score"] == Decimal("0.0450")
    assert record["feature_snapshot"]["amount_scaled"] == 1.25

    # 3. Test ON CONFLICT (transaction_ref) DO NOTHING idempotency
    dup_inserted = await repo.save_transactions_batch(decisions)
    assert dup_inserted == 0  # Ignored duplicate without error

    total = await repo.count_transactions()
    assert total == 1


@pytest.mark.asyncio
async def test_repository_queries_and_summary(repo: TransactionRepository) -> None:
    """Test user recent queries and aggregate status summary."""
    u1 = str(uuid4())
    u2 = str(uuid4())

    batch = [
        {
            "transaction_id": f"tx_app_{i}",
            "user_id": u1,
            "account_id": str(uuid4()),
            "amount": 50.0 + i,
            "status": "APPROVED",
            "risk_score": 0.10,
            "timestamp": f"2026-10-22T10:0{i}:00Z",
        }
        for i in range(3)
    ]
    batch.append(
        {
            "transaction_id": "tx_rej_1",
            "user_id": u2,
            "account_id": str(uuid4()),
            "amount": 5000.0,
            "status": "REJECTED",
            "risk_score": 0.95,
            "timestamp": "2026-10-22T11:00:00Z",
        }
    )
    batch.append(
        {
            "transaction_id": "tx_flg_1",
            "user_id": u1,
            "account_id": str(uuid4()),
            "amount": 350.0,
            "status": "FLAGGED",
            "risk_score": 0.60,
            "timestamp": "2026-10-22T12:00:00Z",
        }
    )

    await repo.save_transactions_batch(batch)

    # User recent queries
    u1_txs = await repo.get_user_recent_transactions(u1, limit=10)
    assert len(u1_txs) == 4
    assert u1_txs[0]["status"] == "FLAGGED"  # Most recent

    # Status summary
    summary = await repo.get_status_summary()
    assert summary["total"] == 5
    assert summary["approved_count"] == 3
    assert summary["flagged_count"] == 1
    assert summary["rejected_count"] == 1
    assert summary["total_volume"] == 50.0 + 51.0 + 52.0 + 5000.0 + 350.0

    # Empty batch returns 0
    assert await repo.save_transactions_batch([]) == 0


@pytest.mark.asyncio
async def test_persistence_buffer_size_trigger(repo: TransactionRepository) -> None:
    """Verify that buffer automatically flushes when reaching batch_size."""
    batch_size = 5
    buffer = PersistenceBuffer(
        repository=repo,
        batch_size=batch_size,
        flush_interval_seconds=1.0,  # Long interval so time trigger doesn't fire early
    )
    await buffer.start()

    try:
        # Enqueue exactly batch_size items
        for i in range(batch_size):
            await buffer.add(
                {
                    "transaction_id": f"tx_size_{i}",
                    "user_id": str(uuid4()),
                    "account_id": str(uuid4()),
                    "amount": 25.0,
                    "status": "APPROVED",
                }
            )

        # Allow micro-task switch for worker loop
        await asyncio.sleep(0.05)

        # Verify batch was flushed
        assert buffer.total_flushed == batch_size
        assert buffer.batches_count >= 1
    finally:
        await buffer.stop()


@pytest.mark.asyncio
async def test_persistence_buffer_time_trigger(repo: TransactionRepository) -> None:
    """Verify that buffer flushes after flush_interval even if batch_size is not reached."""
    batch_size = 50
    flush_interval = 0.05  # 50 ms
    buffer = PersistenceBuffer(
        repository=repo,
        batch_size=batch_size,
        flush_interval_seconds=flush_interval,
    )
    await buffer.start()

    try:
        # Enqueue only 3 items (< 50)
        for i in range(3):
            await buffer.add(
                {
                    "transaction_id": f"tx_time_{i}",
                    "user_id": str(uuid4()),
                    "account_id": str(uuid4()),
                    "amount": 10.0,
                    "status": "APPROVED",
                }
            )

        # Before interval: items are in queue
        assert buffer.total_flushed == 0

        # Wait past flush interval
        await asyncio.sleep(0.12)

        # Verify time-based flush occurred
        assert buffer.total_flushed == 3
        assert buffer.batches_count >= 1
    finally:
        await buffer.stop()


@pytest.mark.asyncio
async def test_persistence_buffer_drain_on_stop(repo: TransactionRepository) -> None:
    """Verify that stop() drains any pending buffered items cleanly."""
    buffer = PersistenceBuffer(
        repository=repo,
        batch_size=100,
        flush_interval_seconds=10.0,  # Never flushes automatically
    )
    # Note: we do not even need to start worker loop
    for i in range(10):
        await buffer.add(
            {
                "transaction_id": f"tx_drain_{i}",
                "user_id": str(uuid4()),
                "account_id": str(uuid4()),
                "amount": 99.0,
                "status": "APPROVED",
            }
        )

    assert buffer.queue.qsize() == 10
    # Stop flushes all pending items
    await buffer.stop()
    assert buffer.queue.empty()
    assert buffer.total_flushed == 10
    assert await repo.count_transactions() == 10


@pytest.mark.asyncio
async def test_fraud_consumer_with_persistence_integration() -> None:
    """Test FraudConsumer running synthetic transactions with micro-batch persistence."""
    pool = PostgresPool(mock_mode=True)
    repo = TransactionRepository(pool)
    buffer = PersistenceBuffer(
        repository=repo,
        batch_size=5,
        flush_interval_seconds=0.02,
    )

    consumer = FraudConsumer(
        mock_mode=True,
        persistence_buffer=buffer,
        enable_persistence=True,
    )

    # Run for 15 synthetic messages
    await consumer.start(max_messages=15)

    assert consumer.processed_count == 15
    assert consumer.persistence_buffer.total_enqueued == 15
    assert consumer.persistence_buffer.total_flushed == 15
    assert await repo.count_transactions() == 15

    # Verify status summary
    summary = await repo.get_status_summary()
    assert summary["total"] == 15
    assert summary["total_volume"] > 0
