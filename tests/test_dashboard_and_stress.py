"""Stage 10 Test Suite: Operational Dashboard, Stress Benchmark & Chaos Resilience.

Validates:
1. Dashboard HTML5 structure, semantic containers, and critical element IDs.
2. Dashboard JavaScript resilience, WebSocket reconnection logic, and Web Audio synthesis.
3. Stress testing benchmark harness, percentile calculations, and SLA verification.
4. Chaos testing harness, worker crash simulation, offset recovery, and DB deduplication.
5. In-memory partitioned Kafka topic log simulation mechanics.
"""

from pathlib import Path
import pytest

from scripts.chaos_test import ChaosTestRunner, MockKafkaTopic
from scripts.stress_test import StressBenchmarkResult, StressTestHarness


@pytest.fixture
def repo_root() -> Path:
    """Return repository root path."""
    return Path(__file__).resolve().parent.parent


class TestDashboardStaticAssets:
    """Test frontend static assets and DOM contract for operational dashboard."""

    def test_dashboard_html_structure(self, repo_root: Path) -> None:
        """Verify dashboard/index.html contains all required containers and element IDs."""
        html_file = repo_root / "dashboard" / "index.html"
        assert html_file.exists(), "dashboard/index.html does not exist"

        content = html_file.read_text(encoding="utf-8")

        # 1. Page title & meta
        assert "<title>Real-Time Fraud Detection" in content
        assert '<meta name="viewport"' in content

        # 2. WebSocket Status
        assert 'id="ws-status-badge"' in content
        assert 'id="ws-status-text"' in content

        # 3. KPI Telemetry Elements
        assert 'id="kpi-tps"' in content
        assert 'id="kpi-latency"' in content
        assert 'id="kpi-total-alerts"' in content
        assert 'id="kpi-total-processed"' in content
        assert 'id="kpi-flagged"' in content
        assert 'id="kpi-rejected"' in content

        # 4. Action Buttons & Controls
        assert 'id="trigger-sim-btn"' in content
        assert 'id="clear-feed-btn"' in content
        assert 'id="toggle-sound-btn"' in content

        # 5. Core Operational Feeds
        assert 'id="alerts-container"' in content
        assert 'id="ticker-container"' in content

    def test_dashboard_javascript_resilience(self, repo_root: Path) -> None:
        """Verify dashboard/app.js implements resilient reconnects, audio synthesis and hydration."""
        js_file = repo_root / "dashboard" / "app.js"
        assert js_file.exists(), "dashboard/app.js does not exist"

        content = js_file.read_text(encoding="utf-8")

        # 1. Resilient WebSocket reconnection with backoff
        assert "reconnectattempts" in content.lower()
        assert "maxreconnectdelay" in content.lower()
        assert "schedulereconnect" in content.lower()

        # 2. REST initial hydration
        assert "/api/v1/alerts/recent" in content

        # 3. Web Audio API alert synthesis
        assert "AudioContext" in content
        assert "playAlertChime" in content

        # 4. Attack simulation handler
        assert "DEMO_ATTACK_PATTERNS" in content
        assert "triggerSimBtn" in content


class TestStressBenchmarkHarness:
    """Test stress testing harness and latency calculation logic."""

    @pytest.mark.asyncio
    async def test_stress_harness_mock_execution(self) -> None:
        """Execute short mock stress benchmark and verify SLA calculations."""
        harness = StressTestHarness(
            tps=50.0,
            total_events=30,
            concurrency=5,
            mock_mode=True,
        )

        result = await harness.run()
        assert isinstance(result, StressBenchmarkResult)
        assert result.total_events == 30
        assert result.achieved_tps > 0
        assert result.p50_latency_ms <= result.p90_latency_ms
        assert result.p90_latency_ms <= result.p95_latency_ms
        assert result.p95_latency_ms <= result.p99_latency_ms
        assert result.p95_latency_ms < 50.0, f"P95 latency {result.p95_latency_ms} ms breached SLA"
        assert result.passed_sla is True

    def test_stress_percentile_calculation_edge_cases(self) -> None:
        """Test percentile computation with varying sample sizes."""
        result = StressBenchmarkResult()
        # Empty list fallback
        assert result.calculate_percentile([], 95.0) == 0.0

        # Single element
        assert result.calculate_percentile([12.5], 95.0) == 12.5

        # Monotonic distribution
        samples = [float(i) for i in range(1, 101)]  # 1.0 to 100.0
        p50 = result.calculate_percentile(samples, 50.0)
        p95 = result.calculate_percentile(samples, 95.0)
        p99 = result.calculate_percentile(samples, 99.0)
        assert p50 == pytest.approx(50.0, abs=1.5)
        assert p95 == pytest.approx(95.0, abs=1.5)
        assert p99 == pytest.approx(99.0, abs=1.5)


class TestChaosResilienceHarness:
    """Test chaos engineering, worker crash, offset recovery, and DB deduplication."""

    def test_mock_kafka_topic_semantics(self) -> None:
        """Verify mock partitioned topic log maintains offsets and lag accurately."""
        topic = MockKafkaTopic("test-topic")
        group = "test-group"

        assert topic.get_high_watermark() == 0
        assert topic.get_committed_offset(group) == 0
        assert topic.get_lag(group) == 0

        # Produce 5 events
        for i in range(5):
            off = topic.produce({"id": i, "val": f"payload_{i}"})
            assert off == i

        assert topic.get_high_watermark() == 5
        assert topic.get_lag(group) == 5

        # Fetch and commit 2 events
        fetched = topic.fetch(0, limit=2)
        assert len(fetched) == 2
        assert fetched[0][0] == 0
        assert fetched[1][0] == 1

        topic.commit_offset(group, 2)
        assert topic.get_committed_offset(group) == 2
        assert topic.get_lag(group) == 3

    @pytest.mark.asyncio
    async def test_chaos_runner_lifecycle(self) -> None:
        """Run full chaos crash, backlog buildup, recovery, and idempotency check."""
        runner = ChaosTestRunner(
            mock_mode=True,
            group_id="test-chaos-group",
        )

        result = await runner.run(
            baseline_count=15,
            chaos_count=10,
            outage_count=10,
        )

        assert result.passed is True
        assert result.total_produced == 35
        assert result.baseline_processed == 15
        assert result.uncommitted_on_crash == 5
        assert result.backlog_accumulated == 20
        assert result.recovery_processed == 20
        assert result.total_stored_in_db == 35
        assert result.duplicate_rows_detected == 0
        assert result.dropped_transactions == 0
        assert result.final_consumer_lag == 0
