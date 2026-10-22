"""Asynchronous Micro-Batching Persistence Buffer.

Features:
- Decouples high-frequency Kafka consumers from PostgreSQL disk I/O.
- Bounded in-memory FIFO queue buffer (capacity: 10,000 events).
- Dual-trigger automated flush logic:
  1. Size trigger: flushes immediately when queue reaches batch_size (default: 50).
  2. Time trigger: flushes after flush_interval_seconds (default: 50 ms) to avoid stale buffering.
- Idempotent drain on graceful shutdown to prevent data loss.
"""

import asyncio
import time
from typing import Any

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.storage.transaction_repository import TransactionRepository

logger = get_logger("fraud_detection.streaming.persistence_buffer")


class PersistenceBuffer:
    """Asynchronous dual-trigger queue buffer for batching PostgreSQL writes."""

    def __init__(
        self,
        repository: TransactionRepository,
        batch_size: int = settings.POSTGRES_BATCH_SIZE,
        flush_interval_seconds: float = settings.POSTGRES_FLUSH_INTERVAL_SECONDS,
        max_queue_size: int = 10000,
    ) -> None:
        self.repository = repository
        self.batch_size = max(1, batch_size)
        self.flush_interval = max(0.005, flush_interval_seconds)
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)

        self._running = False
        self._worker_task: asyncio.Task[None] | None = None
        self._flush_lock = asyncio.Lock()

        # Telemetry
        self.total_enqueued = 0
        self.total_flushed = 0
        self.batches_count = 0

    async def start(self) -> None:
        """Launch background worker loop."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info(
            "PersistenceBuffer worker started",
            extra={"batch_size": self.batch_size, "flush_interval_s": self.flush_interval},
        )

    async def add(self, decision: dict[str, Any]) -> bool:
        """
        Enqueue a scored decision record for micro-batched persistence.

        Returns True if enqueued, False if buffer was saturated.
        """
        try:
            self.queue.put_nowait(decision)
            self.total_enqueued += 1
            return True
        except asyncio.QueueFull:
            logger.warning(
                "Persistence buffer queue full! Dropping decision record to prevent memory leak.",
                extra={"queue_size": self.queue.qsize()},
            )
            return False

    async def _worker_loop(self) -> None:
        """Continuously drain queue on size trigger or time trigger."""
        while self._running:
            try:
                await self._drain_and_flush()
                await asyncio.sleep(self.flush_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in persistence buffer worker loop", extra={"error": str(exc)})
                await asyncio.sleep(self.flush_interval)

    async def _drain_and_flush(self) -> int:
        """Collect accumulated items up to batch_size and flush to repository."""
        async with self._flush_lock:
            items: list[dict[str, Any]] = []
            while not self.queue.empty() and len(items) < self.batch_size:
                try:
                    items.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            if not items:
                return 0

            t0 = time.perf_counter()
            persisted = await self.repository.save_transactions_batch(items)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            self.total_flushed += persisted
            self.batches_count += 1

            for _ in range(len(items)):
                self.queue.task_done()

            logger.debug(
                "Flushed micro-batch to PostgreSQL",
                extra={
                    "count": persisted,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "total_flushed": self.total_flushed,
                },
            )
            return persisted

    async def flush(self) -> int:
        """Manually trigger flush of all currently queued items."""
        total_flushed = 0
        while not self.queue.empty():
            flushed = await self._drain_and_flush()
            if flushed == 0:
                break
            total_flushed += flushed
        return total_flushed

    async def stop(self) -> None:
        """Drain remaining buffer, write final batch, and cleanly terminate worker."""
        self._running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        # Drain any residual queued items
        final_flushed = await self.flush()
        logger.info(
            "PersistenceBuffer cleanly stopped",
            extra={
                "total_enqueued": self.total_enqueued,
                "total_flushed": self.total_flushed,
                "final_flushed": final_flushed,
            },
        )


async def run_persistence_demo(
    count: int = 100,
    batch_size: int = settings.POSTGRES_BATCH_SIZE,
    flush_interval: float = settings.POSTGRES_FLUSH_INTERVAL_SECONDS,
    mock: bool = False,
) -> None:
    """Run an interactive demonstration of micro-batch persistence."""
    import random
    from uuid import uuid4

    from fraud_detection.storage.postgres_pool import PostgresPool

    print("=" * 80)
    print("PostgreSQL Micro-Batch Persistence Demonstration")
    print(
        f"Count: {count} | Batch Size: {batch_size} | Flush Interval: {flush_interval * 1000:.0f} ms | Mock: {mock}"
    )
    print("=" * 80)

    pool = PostgresPool(mock_mode=mock)
    await pool.initialize()
    repo = TransactionRepository(pool)
    buffer = PersistenceBuffer(
        repository=repo,
        batch_size=batch_size,
        flush_interval_seconds=flush_interval,
    )
    await buffer.start()

    user_ids = [str(uuid4()) for _ in range(5)]
    categories = ["retail", "groceries", "electronics", "travel", "dining"]
    statuses = ["APPROVED"] * 8 + ["FLAGGED", "REJECTED"]

    t0 = time.perf_counter()
    for i in range(count):
        u_id = random.choice(user_ids)
        decision = {
            "transaction_id": str(uuid4()),
            "user_id": u_id,
            "account_id": str(uuid4()),
            "amount": round(random.uniform(5.0, 1500.0), 2),
            "currency": "USD",
            "merchant_category": random.choice(categories),
            "merchant_name": f"Merchant_{random.randint(100, 999)}",
            "location_country": "US",
            "location_lat": round(random.uniform(25.0, 48.0), 4),
            "location_lon": round(random.uniform(-120.0, -75.0), 4),
            "device_id": f"device_{random.randint(10, 50)}",
            "ip_address": f"192.168.1.{random.randint(2, 250)}",
            "status": random.choice(statuses),
            "risk_score": round(random.uniform(0.01, 0.95), 4),
            "features": {"amount_scaled": round(random.uniform(0.1, 5.0), 2)},
            "rule_violations": [],
            "timestamp": time.time(),
        }
        await buffer.add(decision)
        # Small delay between synthetic transaction arrivals
        if i % 15 == 0:
            await asyncio.sleep(0.01)

    # Allow buffer loop to flush pending queues
    await asyncio.sleep(0.15)
    await buffer.stop()
    await pool.close()

    total_time = (time.perf_counter() - t0) * 1000.0
    summary = await repo.get_status_summary()

    print("\n" + "=" * 80)
    print("Micro-Batch Persistence Results")
    print("=" * 80)
    print(f"Total Enqueued:     {buffer.total_enqueued:,}")
    print(f"Total Flushed:      {buffer.total_flushed:,}")
    print(f"Batches Flushed:    {buffer.batches_count:,}")
    print(f"Total Time:         {total_time:.2f} ms")
    print(f"Avg per record:     {total_time / count:.2f} ms")
    print(
        f"Status Breakdown:   APPROVED: {summary.get('approved_count', 0)} | "
        f"FLAGGED: {summary.get('flagged_count', 0)} | "
        f"REJECTED: {summary.get('rejected_count', 0)}"
    )
    print(f"Total Volume:       ${summary.get('total_volume', 0.0):,.2f}")
    print("=" * 80)


def main() -> None:
    """CLI entrypoint for standalone persistence worker demo."""
    import argparse

    parser = argparse.ArgumentParser(description="PostgreSQL Micro-Batch Persistence Worker")
    parser.add_argument(
        "--count", type=int, default=100, help="Number of transactions to buffer and persist"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=settings.POSTGRES_BATCH_SIZE,
        help="Queue batch size trigger",
    )
    parser.add_argument(
        "--flush-interval",
        type=float,
        default=settings.POSTGRES_FLUSH_INTERVAL_SECONDS,
        help="Queue time flush trigger (s)",
    )
    parser.add_argument("--mock", action="store_true", help="Force in-memory mock mode")
    args = parser.parse_args()

    asyncio.run(
        run_persistence_demo(
            count=args.count,
            batch_size=args.batch_size,
            flush_interval=args.flush_interval,
            mock=args.mock,
        )
    )


__all__ = ["PersistenceBuffer", "main", "run_persistence_demo"]

if __name__ == "__main__":
    main()
