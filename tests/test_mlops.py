"""Unit and Integration Tests for Stage 11 MLOps Subsystem.

Validates:
1. ExperimentTracker lifecycle, parameter logging, metric histories, and artifact logging.
2. ModelRegistry candidate registration, stage transitions, and automated promotion gates.
3. DriftDetector PSI calculations, two-sample KS-test statistics, and concept drift alerting.
4. RetrainingPipeline drift detection gating and automated continuous retraining workflows.
"""

from pathlib import Path
import numpy as np
import pytest

from fraud_detection.ml.data_loader import generate_10k_realistic_transactions
from fraud_detection.mlops.drift_detector import DriftDetector
from fraud_detection.mlops.pipeline import RetrainingPipeline
from fraud_detection.mlops.registry import ModelRegistry
from fraud_detection.mlops.tracking import ExperimentTracker


@pytest.fixture
def temp_mlops_env(tmp_path: Path):
    """Provide isolated directory environments for tracking and registry testing."""
    runs_dir = tmp_path / "mlruns"
    registry_dir = tmp_path / "model_registry"
    runs_dir.mkdir(parents=True, exist_ok=True)
    registry_dir.mkdir(parents=True, exist_ok=True)

    tracker = ExperimentTracker(experiment_name="test-experiment", local_store_dir=runs_dir)
    registry = ModelRegistry(
        registry_dir=registry_dir, production_model_path=tmp_path / "fraud_model.joblib"
    )
    detector = DriftDetector()

    return {
        "tracker": tracker,
        "registry": registry,
        "detector": detector,
        "tmp_path": tmp_path,
        "runs_dir": runs_dir,
        "registry_dir": registry_dir,
    }


# =====================================================================
# 1. ExperimentTracker Tests
# =====================================================================


def test_experiment_tracker_run_lifecycle(temp_mlops_env):
    """Test start_run, parameter logging, metric tracking, artifact logging, and run completion."""
    tracker: ExperimentTracker = temp_mlops_env["tracker"]
    tmp_path: Path = temp_mlops_env["tmp_path"]

    # Create dummy artifact file
    dummy_artifact = tmp_path / "dummy_weights.txt"
    dummy_artifact.write_text("dummy model weights content", encoding="utf-8")

    run_ctx = tracker.start_run(run_name="unit_test_run", tags={"environment": "test"})
    assert run_ctx.run_id is not None
    assert tracker.active_run is not None

    run_ctx.log_params({"n_estimators": 100, "learning_rate": 0.05})
    run_ctx.log_metrics({"pr_auc": 0.895, "f1_score": 0.842})
    run_ctx.log_artifact(str(dummy_artifact))

    tracker.end_run(status="FINISHED")
    assert tracker.active_run is None

    # Search runs to verify persistence
    runs = tracker.search_runs()
    assert len(runs) >= 1
    latest_run = runs[0]
    assert latest_run.get("run_name") == "unit_test_run"
    assert latest_run.get("params", {}).get("n_estimators") == 100
    assert latest_run.get("metrics", {}).get("pr_auc") == 0.895
    assert latest_run.get("status") == "FINISHED"


def test_experiment_tracker_context_manager(temp_mlops_env):
    """Verify context manager handles successful runs and records failure on exception."""
    tracker: ExperimentTracker = temp_mlops_env["tracker"]

    # Successful block
    with tracker.start_run(run_name="cm_success_run") as ctx:
        ctx.log_metrics({"accuracy": 0.99})
    assert tracker.active_run is None

    # Exception block
    with pytest.raises(RuntimeError):
        with tracker.start_run(run_name="cm_error_run") as ctx:
            ctx.log_metrics({"accuracy": 0.50})
            raise RuntimeError("Simulated pipeline crash during training")

    assert tracker.active_run is None
    runs = tracker.search_runs()
    error_run = next(r for r in runs if r.get("run_name") == "cm_error_run")
    assert error_run.get("status") == "FAILED"


# =====================================================================
# 2. ModelRegistry Governance & Gate Tests
# =====================================================================


def test_model_registry_registration_and_versioning(temp_mlops_env):
    """Test model registration auto-increments version and sets Development stage."""
    registry: ModelRegistry = temp_mlops_env["registry"]
    tmp_path: Path = temp_mlops_env["tmp_path"]

    dummy_model = tmp_path / "model.joblib"
    dummy_model.write_text("model_bytes", encoding="utf-8")

    v1 = registry.register_candidate(
        model_name="fraud-detector",
        run_id="run_101",
        metrics={"pr_auc": 0.88, "f1_score": 0.82},
        artifact_path=dummy_model,
        description="First candidate",
    )
    assert v1.version == 1
    assert v1.stage == "Development"

    v2 = registry.register_candidate(
        model_name="fraud-detector",
        run_id="run_102",
        metrics={"pr_auc": 0.91, "f1_score": 0.85},
        artifact_path=dummy_model,
        description="Second candidate",
    )
    assert v2.version == 2
    assert v2.stage == "Development"

    history = registry.get_version_history("fraud-detector")
    assert len(history) == 2


def test_model_registry_promotion_gates_pass(temp_mlops_env):
    """Verify candidate meeting all criteria passes automated promotion gate."""
    registry: ModelRegistry = temp_mlops_env["registry"]
    tmp_path: Path = temp_mlops_env["tmp_path"]

    dummy_model = tmp_path / "model_high_quality.joblib"
    dummy_model.write_text("quality_bytes", encoding="utf-8")

    version = registry.register_candidate(
        model_name="fraud-detector",
        run_id="run_pass",
        metrics={
            "pr_auc": 0.910,
            "f1_score": 0.860,
            "inference_latency_p95_ms": 1.75,
            "fpr": 0.015,
        },
        artifact_path=dummy_model,
    )

    gate_result = registry.evaluate_gates(version)
    assert gate_result.passed is True
    assert len(gate_result.failure_reasons) == 0

    promoted, gate_res = registry.promote_to_production(
        model_name="fraud-detector",
        version=version.version,
        deploy_to_artifacts=False,
    )
    assert promoted.stage == "Production"
    assert gate_res.passed is True


def test_model_registry_promotion_gates_fail(temp_mlops_env):
    """Verify candidate violating SLA latency or minimum PR-AUC is rejected."""
    registry: ModelRegistry = temp_mlops_env["registry"]
    tmp_path: Path = temp_mlops_env["tmp_path"]

    dummy_model = tmp_path / "model_poor_quality.joblib"
    dummy_model.write_text("poor_bytes", encoding="utf-8")

    # Sub-par model: low PR-AUC and high latency
    version = registry.register_candidate(
        model_name="fraud-detector",
        run_id="run_fail",
        metrics={
            "pr_auc": 0.620,  # Below 0.850
            "f1_score": 0.550,  # Below 0.800
            "inference_latency_p95_ms": 5.40,  # Exceeds 3.0 ms budget
            "fpr": 0.08,  # Exceeds 0.05
        },
        artifact_path=dummy_model,
    )

    gate_result = registry.evaluate_gates(version)
    assert gate_result.passed is False
    assert len(gate_result.failure_reasons) >= 3

    # Attempt promotion without force should fail
    candidate, gate_res = registry.promote_to_production(
        model_name="fraud-detector",
        version=version.version,
        force=False,
        deploy_to_artifacts=False,
    )
    assert candidate.stage == "Development"
    assert gate_res.passed is False


def test_model_registry_champion_demotion(temp_mlops_env):
    """Verify previous champion is demoted to Archived when new champion is promoted."""
    registry: ModelRegistry = temp_mlops_env["registry"]
    tmp_path: Path = temp_mlops_env["tmp_path"]

    dummy_model = tmp_path / "model_cycle.joblib"
    dummy_model.write_text("cycle_bytes", encoding="utf-8")

    v1 = registry.register_candidate(
        model_name="fraud-detector",
        run_id="run_v1",
        metrics={"pr_auc": 0.88, "f1_score": 0.82, "latency_ms": 1.5, "fpr": 0.02},
        artifact_path=dummy_model,
    )
    registry.promote_to_production("fraud-detector", v1.version, deploy_to_artifacts=False)

    champion = registry.get_champion("fraud-detector")
    assert champion is not None
    assert champion.version == 1

    # Register and promote v2
    v2 = registry.register_candidate(
        model_name="fraud-detector",
        run_id="run_v2",
        metrics={"pr_auc": 0.94, "f1_score": 0.88, "latency_ms": 1.2, "fpr": 0.01},
        artifact_path=dummy_model,
    )
    registry.promote_to_production("fraud-detector", v2.version, deploy_to_artifacts=False)

    # v1 must now be Archived and v2 is Production
    old_v1 = registry.get_model_version("fraud-detector", 1)
    new_v2 = registry.get_model_version("fraud-detector", 2)
    assert old_v1.stage == "Archived"
    assert new_v2.stage == "Production"


# =====================================================================
# 3. DriftDetector Tests (PSI, KS-Test & Concept Drift)
# =====================================================================


def test_psi_identical_distribution(temp_mlops_env):
    """Identical distributions must have PSI score of 0.0."""
    detector: DriftDetector = temp_mlops_env["detector"]
    data = np.random.normal(loc=100.0, scale=15.0, size=1000)

    psi = detector.calculate_psi(data, data)
    assert psi == 0.0


def test_psi_stable_distribution(temp_mlops_env):
    """Small sample variation drawn from same distribution must yield PSI < 0.10 (STABLE)."""
    detector: DriftDetector = temp_mlops_env["detector"]
    np.random.seed(42)
    baseline = np.random.normal(loc=100.0, scale=15.0, size=2000)
    current = np.random.normal(loc=100.2, scale=15.1, size=2000)

    psi = detector.calculate_psi(baseline, current)
    assert psi < 0.10


def test_psi_and_ks_severe_drift(temp_mlops_env):
    """Significant mean/scale shift must trigger SEVERE_DRIFT with PSI >= 0.25 and KS p < 0.001."""
    detector: DriftDetector = temp_mlops_env["detector"]
    np.random.seed(42)
    baseline = np.random.normal(loc=50.0, scale=10.0, size=2000)
    current = np.random.normal(loc=250.0, scale=80.0, size=2000)  # Extreme shift

    res = detector.evaluate_feature("amount", baseline, current)
    assert res.psi_score >= 0.25
    assert res.drift_severity == "SEVERE_DRIFT"
    assert res.drift_detected is True
    assert res.ks_p_value < 0.001


def test_concept_drift_alert_rate_jump(temp_mlops_env):
    """A sudden spike in fraud prediction alert rate must trigger concept drift detection."""
    detector: DriftDetector = temp_mlops_env["detector"]
    # Baseline: 1.0% alert rate
    baseline_preds = np.array([0.9] * 10 + [0.05] * 990)
    # Current: 7.0% alert rate
    current_preds = np.array([0.9] * 70 + [0.05] * 930)

    concept_report = detector.evaluate_concept_drift(
        baseline_predictions=baseline_preds,
        current_predictions=current_preds,
        alert_threshold=0.50,
    )

    assert concept_report["concept_drift_detected"] is True
    assert concept_report["status"] == "CONCEPT_DRIFT_ALERT"
    assert concept_report["baseline_alert_rate"] == 0.010
    assert concept_report["current_alert_rate"] == 0.070


# =====================================================================
# 4. RetrainingPipeline Integration Tests
# =====================================================================


def test_retraining_pipeline_skipped_when_stable(temp_mlops_env):
    """Pipeline skips retraining when data distributions are statistically stable."""
    tracker = temp_mlops_env["tracker"]
    registry = temp_mlops_env["registry"]
    detector = temp_mlops_env["detector"]

    pipeline = RetrainingPipeline(
        model_name="fraud-detector-test",
        tracker=tracker,
        registry=registry,
        drift_detector=detector,
    )

    # Generate synthetic reference and identical stable batch
    test_csv_1 = temp_mlops_env["tmp_path"] / "test_base_1.csv"
    base_df = generate_10k_realistic_transactions(
        output_path=test_csv_1, n_samples=500, random_seed=42
    )
    current_df = base_df.sample(n=300, random_state=42).copy().reset_index(drop=True)

    result = pipeline.run_pipeline(
        baseline_df=base_df,
        current_df=current_df,
        force=False,
        simulate_drift=False,
        deploy=False,
    )

    assert result["retrained"] is False
    assert result["status"] == "SKIPPED_NO_DRIFT"


def test_retraining_pipeline_drift_trigger_and_promotion(temp_mlops_env):
    """Pipeline triggers candidate training and registry promotion when drift is detected."""
    tracker = temp_mlops_env["tracker"]
    registry = temp_mlops_env["registry"]
    detector = temp_mlops_env["detector"]

    pipeline = RetrainingPipeline(
        model_name="fraud-detector-test",
        tracker=tracker,
        registry=registry,
        drift_detector=detector,
    )

    # Base dataset with sufficient fraud samples for validation optimization
    test_csv_2 = temp_mlops_env["tmp_path"] / "test_base_2.csv"
    base_df = generate_10k_realistic_transactions(
        output_path=test_csv_2, n_samples=2500, fraud_rate=0.03, random_seed=42
    )

    result = pipeline.run_pipeline(
        baseline_df=base_df,
        force=False,
        simulate_drift=True,  # Injects severe distribution shift
        deploy=False,  # Isolated run
    )

    assert result["retrained"] is True
    assert result["status"] == "COMPLETED"
    assert result["candidate_version"] >= 1
    assert result["gate_passed"] is True
    assert result["metrics"]["pr_auc"] >= 0.850
