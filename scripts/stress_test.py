"""End-to-End Stress Testing & Latency Profiling Harness (Stage 10).

Executes sustained high-throughput (100+ TPS) transactional stress testing,
measuring end-to-end latency percentiles (p50, p90, p95, p99) across every pipeline hop:
1. Feature Store velocity extraction (Redis Sorted Sets)
2. Hybrid ML model scoring (LightGBM + Isolation Forest)
3. Deterministic compliance rule evaluation
4. PostgreSQL micro-batch persistence
5. Alert fan-out broadcasting

Supports both live infrastructure mode and zero-dependency offline simulation mode (--mock).

Usage:
    uv run python scripts/stress_test.py --tps 100 --total-events 500 --mock
    or
    uv run fraud-stress-test --tps 100 --duration 10
"""

import argparse
import asyncio
from dataclasses import dataclass, field
import math
from pathlib import Path
import random
import sys
import time
from typing import Any
import uuid

# Ensure 'src' directory is present in module search path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.ml.features import extract_features
from fraud_detection.ml.inference import InferenceEngine
from fraud_detection.rules.rule_engine import RuleEngine
from fraud_detection.storage.postgres_pool import PostgresPool
from fraud_detection.storage.redis_feature_store import RedisFeatureStore
from fraud_detection.storage.redis_publisher import RedisPublisher
from fraud_detection.storage.transaction_repository import TransactionRepository

logger = get_logger(__name__)


@dataclass
class HopLatencies:
    """Microsecond latency breakdown per pipeline segment."""

    feature_store_ms: float = 0.0
    ml_inference_ms: float = 0.0
    rules_engine_ms: float = 0.0
    db_persistence_ms: float = 0.0
    pubsub_ms: float = 0.0
    total_e2e_ms: float = 0.0


@dataclass
class StressBenchmarkResult:
    """Aggregated stress testing metrics and SLA validation results."""

    total_events: int = 0
    approved_count: int = 0
    flagged_count: int = 0
    rejected_count: int = 0
    duration_seconds: float = 0.0
    achieved_tps: float = 0.0
    latencies_e2e: list[float] = field(default_factory=list)
    hop_feature_store: list[float] = field(default_factory=list)
    hop_ml_inference: list[float] = field(default_factory=list)
    hop_rules_engine: list[float] = field(default_factory=list)
    hop_db_persistence: list[float] = field(default_factory=list)
    hop_pubsub: list[float] = field(default_factory=list)

    def calculate_percentile(self, values: list[float], pct: float) -> float:
        """Calculate the given percentile (0 to 100) from a list of measurements."""
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = int(math.ceil((pct / 100.0) * len(sorted_vals))) - 1
        idx = max(0, min(idx, len(sorted_vals) - 1))
        return sorted_vals[idx]

    @property
    def p50_latency_ms(self) -> float:
        return self.calculate_percentile(self.latencies_e2e, 50.0)

    @property
    def p90_latency_ms(self) -> float:
        return self.calculate_percentile(self.latencies_e2e, 90.0)

    @property
    def p95_latency_ms(self) -> float:
        return self.calculate_percentile(self.latencies_e2e, 95.0)

    @property
    def p99_latency_ms(self) -> float:
        return self.calculate_percentile(self.latencies_e2e, 99.0)

    @property
    def mean_latency_ms(self) -> float:
        return sum(self.latencies_e2e) / len(self.latencies_e2e) if self.latencies_e2e else 0.0

    @property
    def max_latency_ms(self) -> float:
        return max(self.latencies_e2e) if self.latencies_e2e else 0.0

    @property
    def passed_sla(self) -> bool:
        """SLA requirement: p95 end-to-end latency must remain below 30.0 ms."""
        return self.p95_latency_ms < 30.0


class StressTestHarness:
    """High-throughput stress test orchestrator."""

    def __init__(
        self,
        tps: float = 100.0,
        total_events: int = 500,
        concurrency: int = 10,
        anomaly_rate: float = 0.05,
        mock_mode: bool = True,
    ):
        self.target_tps = tps
        self.total_events = total_events
        self.concurrency = concurrency
        self.anomaly_rate = anomaly_rate
        self.mock_mode = mock_mode

        # Subsystems
        self.feature_store = RedisFeatureStore(mock_mode=self.mock_mode)
        self.inference_engine = InferenceEngine()
        self.rule_engine = RuleEngine()
        self.pg_pool = PostgresPool(mock_mode=self.mock_mode)
        self.tx_repo = TransactionRepository(self.pg_pool)
        self.redis_publisher = RedisPublisher(mock_mode=self.mock_mode)

    async def initialize(self) -> None:
        """Initialize all backend connections and in-memory models."""
        await self.feature_store.initialize()
        await self.pg_pool.initialize()
        await self.redis_publisher.initialize()

    async def close(self) -> None:
        """Close connections cleanly."""
        await self.feature_store.close()
        await self.pg_pool.close()
        await self.redis_publisher.close()

    def generate_event(self, idx: int) -> dict[str, Any]:
        """Generate a realistic financial transaction event with controlled anomalies."""
        user_id = str(uuid.uuid4())
        is_anomaly = random.random() < self.anomaly_rate

        if is_anomaly:
            # High-risk profile
            amount = (
                random.uniform(4000.0, 9500.0)
                if random.random() < 0.5
                else random.uniform(1.0, 5.0)
            )
            merchant_cat = random.choice(["jewelry", "crypto", "electronics"])
        else:
            amount = round(random.uniform(12.50, 240.00), 2)
            merchant_cat = random.choice(
                ["grocery", "food_delivery", "coffee", "retail", "transport"]
            )

        now = time.time()
        return {
            "transaction_id": f"tx_stress_{idx}_{uuid.uuid4().hex[:8]}",
            "user_id": user_id,
            "account_id": str(uuid.uuid4()),
            "amount": amount,
            "currency": "USD",
            "merchant_category": merchant_cat,
            "merchant_name": f"Merchant-{merchant_cat.capitalize()}",
            "location_country": "US",
            "location_city": "New York",
            "location_lat": 40.7128,
            "location_lon": -74.0060,
            "device_id": f"dev_{uuid.uuid4().hex[:8]}",
            "ip_address": "198.51.100.22",
            "created_at": now,
        }

    async def process_single_transaction(
        self, event_dict: dict[str, Any]
    ) -> tuple[str, HopLatencies]:
        """Execute full 5-hop transaction pipeline and record microsecond timestamps."""
        t_start = time.perf_counter()
        latencies = HopLatencies()

        # Hop 1: Feature Store Velocity Read/Write
        t_fs0 = time.perf_counter()
        velocity_features = await self.feature_store.update_and_get_velocity_features(
            user_id=event_dict["user_id"],
            transaction_id=event_dict["transaction_id"],
            amount=event_dict["amount"],
            timestamp=event_dict["created_at"],
        )
        latencies.feature_store_ms = (time.perf_counter() - t_fs0) * 1000.0

        # Feature Vector Assembly
        assembled_vector = extract_features(
            transaction=event_dict,
            velocity=velocity_features,
        )

        # Hop 2: Hybrid ML Model Inference
        t_ml0 = time.perf_counter()
        pred = self.inference_engine.predict(assembled_vector)
        lgbm_prob = pred["fraud_probability"]
        anomaly_score = pred["anomaly_score"]
        latencies.ml_inference_ms = (time.perf_counter() - t_ml0) * 1000.0

        # Hop 3: Deterministic Rule Engine Evaluation
        t_rules0 = time.perf_counter()
        rule_eval = self.rule_engine.evaluate(
            transaction=event_dict,
            velocity=velocity_features,
        )
        latencies.rules_engine_ms = (time.perf_counter() - t_rules0) * 1000.0

        # Composite Scoring
        blended = (0.65 * lgbm_prob) + (0.35 * anomaly_score)
        risk_score = min(1.0, blended + rule_eval.total_penalty)

        if rule_eval.override_verdict == "REJECTED" or risk_score >= settings.FRAUD_THRESHOLD_HIGH:
            status = "REJECTED"
        elif rule_eval.override_verdict == "FLAGGED" or risk_score >= settings.FRAUD_THRESHOLD_LOW:
            status = "FLAGGED"
        else:
            status = "APPROVED"

        # Build decision dictionary
        decision = {
            **event_dict,
            "status": status,
            "risk_score": risk_score,
            "fraud_probability": lgbm_prob,
            "anomaly_score": anomaly_score,
            "rule_violations": rule_eval.reasons,
            "features": velocity_features,
            "latency_ms": (time.perf_counter() - t_start) * 1000.0,
        }

        # Hop 4: PostgreSQL Micro-Batch Persistence
        t_db0 = time.perf_counter()
        await self.tx_repo.save_transactions_batch([decision])
        latencies.db_persistence_ms = (time.perf_counter() - t_db0) * 1000.0

        # Hop 5: Redis Pub/Sub Fan-Out (Threat Alerts Only)
        t_pub0 = time.perf_counter()
        if status in ("FLAGGED", "REJECTED"):
            await self.redis_publisher.publish_alert(
                decision=decision,
                velocity=velocity_features,
            )
        latencies.pubsub_ms = (time.perf_counter() - t_pub0) * 1000.0

        latencies.total_e2e_ms = (time.perf_counter() - t_start) * 1000.0
        return status, latencies

    async def run(self) -> StressBenchmarkResult:
        """Execute full stress test at the target TPS rate."""
        result = StressBenchmarkResult()
        print(f"\n{'=' * 75}")
        print("[*] FRAUD DETECTION STREAMING STRESS TEST & LATENCY BENCHMARK (STAGE 10)")
        print(f"{'=' * 75}")
        print(f"Target Throughput : {self.target_tps:.1f} TPS")
        print(f"Total Events      : {self.total_events:,}")
        print(f"Concurrency       : {self.concurrency} workers")
        print(f"Anomaly Injection : {self.anomaly_rate * 100:.1f}%")
        print(
            f"Execution Mode    : {'Simulation (Mock In-Memory)' if self.mock_mode else 'Live Cluster'}"
        )
        print(f"{'=' * 75}\n")

        # Token Bucket Rate Limiter
        tokens = 1.0
        last_refill = time.perf_counter()
        token_rate = self.target_tps
        max_bucket_size = self.target_tps

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for idx in range(self.total_events):
            queue.put_nowait(self.generate_event(idx))

        t_benchmark_start = time.perf_counter()

        async def worker() -> None:
            nonlocal tokens, last_refill
            while not queue.empty():
                try:
                    event = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                # Rate limiting wait
                while True:
                    now = time.perf_counter()
                    elapsed = now - last_refill
                    last_refill = now
                    tokens = min(max_bucket_size, tokens + elapsed * token_rate)

                    if tokens >= 1.0:
                        tokens -= 1.0
                        break
                    await asyncio.sleep(0.001)

                status, lats = await self.process_single_transaction(event)

                result.total_events += 1
                if status == "APPROVED":
                    result.approved_count += 1
                elif status == "FLAGGED":
                    result.flagged_count += 1
                else:
                    result.rejected_count += 1

                result.latencies_e2e.append(lats.total_e2e_ms)
                result.hop_feature_store.append(lats.feature_store_ms)
                result.hop_ml_inference.append(lats.ml_inference_ms)
                result.hop_rules_engine.append(lats.rules_engine_ms)
                result.hop_db_persistence.append(lats.db_persistence_ms)
                result.hop_pubsub.append(lats.pubsub_ms)

                if result.total_events % 100 == 0:
                    pct = (result.total_events / self.total_events) * 100
                    print(
                        f"  [{pct:5.1f}%] Processed {result.total_events:,}/{self.total_events:,} events..."
                    )

                queue.task_done()

        # Launch concurrent worker pool
        workers = [asyncio.create_task(worker()) for _ in range(self.concurrency)]
        await asyncio.gather(*workers)

        t_benchmark_end = time.perf_counter()
        result.duration_seconds = t_benchmark_end - t_benchmark_start
        result.achieved_tps = (
            result.total_events / result.duration_seconds if result.duration_seconds > 0 else 0.0
        )

        self._print_report(result)
        return result

    def _print_report(self, res: StressBenchmarkResult) -> None:
        """Render detailed performance report table."""
        print(f"\n{'-' * 75}")
        print("[*] BENCHMARK EXECUTION SUMMARY")
        print(f"{'-' * 75}")
        print(f"Total Transactions Processed : {res.total_events:,}")
        print(f"Benchmark Duration           : {res.duration_seconds:.2f} s")
        print(
            f"Achieved Throughput          : {res.achieved_tps:.1f} TPS (Target: {self.target_tps:.1f})"
        )
        print(
            f"Decision Breakdown           : Approved: {res.approved_count} ({res.approved_count / res.total_events * 100:.1f}%) | "
            f"Flagged: {res.flagged_count} ({res.flagged_count / res.total_events * 100:.1f}%) | "
            f"Rejected: {res.rejected_count} ({res.rejected_count / res.total_events * 100:.1f}%)"
        )
        print(f"{'-' * 75}")
        print("[*] END-TO-END PIPELINE LATENCY PROFILE (ms)")
        print(f"{'-' * 75}")
        print(f"  Mean Latency               : {res.mean_latency_ms:.3f} ms")
        print(f"  P50 (Median) Latency       : {res.p50_latency_ms:.3f} ms")
        print(f"  P90 Latency                : {res.p90_latency_ms:.3f} ms")
        print(f"  P95 Latency                : {res.p95_latency_ms:.3f} ms")
        print(f"  P99 Latency                : {res.p99_latency_ms:.3f} ms")
        print(f"  Max Latency                : {res.max_latency_ms:.3f} ms")
        print(f"{'-' * 75}")
        print("[*] PER-HOP AVERAGE LATENCY BREAKDOWN (ms)")
        print(f"{'-' * 75}")

        def avg(lst: list[float]) -> float:
            return sum(lst) / len(lst) if lst else 0.0

        print(f"  1. Redis Feature Store     : {avg(res.hop_feature_store):.3f} ms (SLA: < 1.0 ms)")
        print(f"  2. Hybrid ML Inference     : {avg(res.hop_ml_inference):.3f} ms (SLA: < 3.0 ms)")
        print(f"  3. Rule Engine Overrides   : {avg(res.hop_rules_engine):.3f} ms (SLA: < 0.2 ms)")
        print(
            f"  4. PostgreSQL Persistence  : {avg(res.hop_db_persistence):.3f} ms (SLA: < 15.0 ms)"
        )
        print(f"  5. Redis Pub/Sub Fan-Out   : {avg(res.hop_pubsub):.3f} ms (SLA: < 5.0 ms)")
        print(f"{'-' * 75}")

        if res.passed_sla:
            print("[PASS] SLA STATUS : PASSED (P95 < 30.0 ms target)")
        else:
            print("[FAIL] SLA STATUS : VIOLATED (P95 exceeded 30.0 ms)")
        print(f"{'=' * 75}\n")


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end streaming stress test harness (Stage 10)"
    )
    parser.add_argument(
        "--tps",
        type=float,
        default=100.0,
        help="Target transactions per second (default: 100.0)",
    )
    parser.add_argument(
        "--total-events",
        type=int,
        default=500,
        help="Total transactions to process (default: 500)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Concurrent worker count (default: 10)",
    )
    parser.add_argument(
        "--anomaly-rate",
        type=float,
        default=0.05,
        help="Anomaly percentage (default: 0.05)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=True,
        help="Run in offline simulation mode without external containers (default: True)",
    )
    parser.add_argument(
        "--live",
        dest="mock",
        action="store_false",
        help="Run against live Kafka, Redis, and PostgreSQL containers",
    )
    args = parser.parse_args()

    harness = StressTestHarness(
        tps=args.tps,
        total_events=args.total_events,
        concurrency=args.concurrency,
        anomaly_rate=args.anomaly_rate,
        mock_mode=args.mock,
    )

    await harness.initialize()
    try:
        res = await harness.run()
        return 0 if res.passed_sla else 1
    finally:
        await harness.close()


def main() -> None:
    code = asyncio.run(async_main())
    sys.exit(code)


if __name__ == "__main__":
    main()
