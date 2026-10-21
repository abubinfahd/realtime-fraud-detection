"""Benchmark Redis Feature Store latency and throughput under concurrent load.

Validates that trailing sliding-window velocity updates achieve the < 1.0 ms p95 SLA.
"""

import argparse
import asyncio
import time
from uuid import uuid4

import numpy as np

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.storage.redis_feature_store import RedisFeatureStore

logger = get_logger("fraud_detection.storage.benchmark")


async def run_worker(
    store: RedisFeatureStore,
    operations_per_worker: int,
    user_pool: list[str],
    latencies_collector: list[float],
) -> None:
    """Execute a batch of velocity feature update operations for a single concurrent worker."""
    for _ in range(operations_per_worker):
        user_id = user_pool[np.random.randint(0, len(user_pool))]
        tx_id = f"bench_tx_{uuid4().hex[:10]}"
        amount = round(float(np.random.uniform(5.0, 350.0)), 2)

        t0 = time.perf_counter()
        await store.update_and_get_velocity_features(
            user_id=user_id,
            transaction_id=tx_id,
            amount=amount,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        latencies_collector.append(latency_ms)


async def run_benchmark(
    num_ops: int = 5000,
    concurrency: int = 50,
    redis_url: str | None = None,
    mock_mode: bool = False,
) -> dict[str, float]:
    """Execute concurrent benchmark and report latency percentiles."""
    print(f"\n{'=' * 70}")
    print("[*] REDIS 7 REAL-TIME FEATURE STORE BENCHMARK")
    print(f"{'=' * 70}")
    print(f"Total Operations: {num_ops:,}")
    print(f"Concurrency Level: {concurrency}")
    print(f"Mode: {'IN-MEMORY MOCK' if mock_mode else 'LIVE REDIS ENGINE'}")
    print("Target SLA: p95 Latency < 1.0 ms\n")

    store = RedisFeatureStore(redis_url=redis_url, mock_mode=mock_mode)
    await store.initialize()

    # Pre-generate 100 user IDs for realistic user distribution
    user_pool = [str(uuid4()) for _ in range(100)]
    latencies: list[float] = []

    ops_per_worker = max(1, num_ops // concurrency)

    start_time = time.perf_counter()
    tasks = [
        run_worker(
            store=store,
            operations_per_worker=ops_per_worker,
            user_pool=user_pool,
            latencies_collector=latencies,
        )
        for _ in range(concurrency)
    ]

    await asyncio.gather(*tasks)
    total_elapsed = time.perf_counter() - start_time
    await store.close()

    arr = np.array(latencies, dtype=np.float64)
    p50 = float(np.percentile(arr, 50))
    p95 = float(np.percentile(arr, 95))
    p99 = float(np.percentile(arr, 99))
    mean_lat = float(np.mean(arr))
    throughput = float(len(arr) / total_elapsed)

    print(f"{'-' * 70}")
    print(f"Total Completed Ops:  {len(arr):,}")
    print(f"Total Elapsed Time:   {total_elapsed:.3f} s")
    print(f"Throughput:           {throughput:,.1f} ops/sec")
    print(f"Min Latency:          {float(np.min(arr)):.3f} ms")
    print(f"Mean Latency:         {mean_lat:.3f} ms")
    print(f"p50 Latency (Median): {p50:.3f} ms")
    print(f"p95 Latency:          {p95:.3f} ms")
    print(f"p99 Latency:          {p99:.3f} ms")
    print(f"Max Latency:          {float(np.max(arr)):.3f} ms")
    print(f"{'-' * 70}")

    if p95 < 1.0:
        print("[SUCCESS] Latency satisfies < 1.0 ms p95 SLA requirement!\n")
    else:
        print(f"[NOTE] p95 latency is {p95:.3f} ms.\n")

    return {
        "total_ops": float(len(arr)),
        "elapsed_seconds": total_elapsed,
        "throughput_ops_sec": throughput,
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "p99_latency_ms": p99,
        "mean_latency_ms": mean_lat,
    }


def main() -> None:
    """CLI application entrypoint for Redis benchmark."""
    parser = argparse.ArgumentParser(
        description="Redis 7 Real-Time Feature Store Concurrency Benchmark"
    )
    parser.add_argument(
        "--num-ops",
        type=int,
        default=5000,
        help="Total operations to execute across workers (default: 5000)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=50,
        help="Number of concurrent asynchronous workers (default: 50)",
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default=settings.redis_url,
        help=f"Redis connection string (default: {settings.redis_url})",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force in-memory simulation engine without network calls",
    )

    args = parser.parse_args()
    asyncio.run(
        run_benchmark(
            num_ops=args.num_ops,
            concurrency=args.concurrency,
            redis_url=args.redis_url,
            mock_mode=args.mock,
        )
    )


if __name__ == "__main__":
    main()
