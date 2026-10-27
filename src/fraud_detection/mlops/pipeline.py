"""Continuous Retraining Pipeline triggered by Statistical Drift or Schedule.

Orchestrates the complete MLOps retraining lifecycle:
1. Statistical feature (PSI, KS-test) & concept drift detection against reference baselines.
2. Experiment tracking of candidate training runs via ExperimentTracker.
3. Automated model registry governance and promotion gate validation.
4. Production artifact hot-swap and backup management upon gate approval.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import warnings

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.ml.data_loader import load_or_generate_dataset
from fraud_detection.ml.evaluate import evaluate_classifier, find_optimal_f1_threshold
from fraud_detection.ml.features import FEATURE_NAMES
from fraud_detection.ml.inference import InferenceEngine
from fraud_detection.ml.preprocessing import preprocess_dataframe
from fraud_detection.mlops.drift_detector import DriftDetector, DriftReport
from fraud_detection.mlops.registry import ModelRegistry, ModelVersion, PromotionGateResult
from fraud_detection.mlops.tracking import ExperimentTracker

logger = get_logger(__name__)
warnings.filterwarnings("ignore", category=UserWarning)


class RetrainingPipeline:
    """Production-grade automated retraining pipeline for fraud detection models."""

    def __init__(
        self,
        model_name: str = "fraud-detector",
        tracker: ExperimentTracker | None = None,
        registry: ModelRegistry | None = None,
        drift_detector: DriftDetector | None = None,
    ) -> None:
        self.model_name = model_name
        self.tracker = tracker or ExperimentTracker(experiment_name=f"{model_name}-retraining")
        self.registry = registry or ModelRegistry()
        self.drift_detector = drift_detector or DriftDetector()

    def detect_drift(
        self,
        baseline_df: pd.DataFrame,
        current_df: pd.DataFrame,
    ) -> tuple[DriftReport, dict[str, Any]]:
        """Evaluate continuous feature drift (PSI, KS-test) and concept drift."""
        X_base, y_base = preprocess_dataframe(baseline_df)
        X_curr, y_curr = preprocess_dataframe(current_df)

        report = self.drift_detector.evaluate_drift(
            current_df=X_curr,
            baseline_df=X_base,
            feature_columns=FEATURE_NAMES,
        )

        concept_info = self.drift_detector.evaluate_concept_drift(
            baseline_predictions=y_base,
            current_predictions=y_curr,
        )

        if concept_info.get("concept_drift_detected"):
            report.recommendation = "RETRAINING_RECOMMENDED"

        return report, concept_info

    def train_candidate(
        self,
        train_df: pd.DataFrame,
        run_name: str | None = None,
        random_seed: int = 42,
    ) -> tuple[dict[str, Any], dict[str, float], Path]:
        """Train candidate LightGBM and Isolation Forest bundle, tracking metrics and artifact."""
        run_label = run_name or f"retrain_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

        with self.tracker.start_run(run_name=run_label) as run_ctx:
            X, y = preprocess_dataframe(train_df)

            # Stratified split: 70% train, 15% validation, 15% test
            X_train_val, X_test, y_train_val, y_test = train_test_split(
                X, y, test_size=0.15, stratify=y, random_state=random_seed
            )
            X_train, X_val, y_train, y_val = train_test_split(
                X_train_val,
                y_train_val,
                test_size=0.17647,
                stratify=y_train_val,
                random_state=random_seed,
            )

            # Class imbalance weighting
            n_pos = max(int(y_train.sum()), 1)
            imbalance_ratio = float((len(y_train) - n_pos) / n_pos)

            lgb_params = {
                "objective": "binary",
                "boosting_type": "gbdt",
                "n_estimators": 150,
                "learning_rate": 0.05,
                "num_leaves": 31,
                "max_depth": 6,
                "scale_pos_weight": imbalance_ratio,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "random_state": random_seed,
                "n_jobs": -1,
                "verbose": -1,
            }

            X_tr_arr = np.ascontiguousarray(X_train.values, dtype=np.float64)
            X_va_arr = np.ascontiguousarray(X_val.values, dtype=np.float64)
            X_te_arr = np.ascontiguousarray(X_test.values, dtype=np.float64)

            lgb_model = LGBMClassifier(**lgb_params)
            lgb_model.fit(X_tr_arr, y_train, eval_set=[(X_va_arr, y_val)])

            # Isolation Forest
            iso_forest = IsolationForest(
                n_estimators=100,
                contamination=0.01,
                max_samples="auto",
                random_state=random_seed,
                n_jobs=-1,
            )
            iso_forest.fit(X_tr_arr)

            # Switch estimators to single-threaded CPU mode for sub-millisecond inference
            lgb_model.set_params(n_jobs=1)
            iso_forest.set_params(n_jobs=1)

            # Validation threshold & test evaluation
            val_probs = lgb_model.predict_proba(X_va_arr)[:, 1]
            optimal_th = find_optimal_f1_threshold(y_val, val_probs)

            test_probs = lgb_model.predict_proba(X_te_arr)[:, 1]
            eval_results = evaluate_classifier(y_test, test_probs, threshold=optimal_th)

            # Measure inference latency on test set
            benchmark_count = min(len(X_test), 2000)
            engine_samples = X_test.iloc[:benchmark_count].values
            latencies_ms: list[float] = []

            # Create candidate bundle in-memory
            timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            candidate_filename = f"candidate_model_{timestamp_str}.joblib"
            candidate_path = settings.ARTIFACTS_DIR / candidate_filename
            settings.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

            bundle = {
                "version": f"retrain-{timestamp_str}",
                "trained_at": datetime.now(UTC).isoformat(),
                "feature_names": FEATURE_NAMES,
                "supervised_model": lgb_model,
                "unsupervised_model": iso_forest,
                "thresholds": {
                    "fraud_low": settings.FRAUD_THRESHOLD_LOW,
                    "fraud_high": settings.FRAUD_THRESHOLD_HIGH,
                    "anomaly_cutoff": settings.ANOMALY_THRESHOLD,
                    "optimal_f1_threshold": optimal_th,
                },
                "metrics": {
                    "test_pr_auc": eval_results["pr_auc"],
                    "test_roc_auc": eval_results["roc_auc"],
                    "test_f1": eval_results["f1_score"],
                    "test_precision": eval_results["precision"],
                    "test_recall": eval_results["recall"],
                },
            }
            joblib.dump(bundle, candidate_path, compress=3)

            # Benchmark single-transaction CPU inference latency
            engine = InferenceEngine(model_path=candidate_path)
            for i in range(min(50, len(engine_samples))):
                _ = engine.predict(engine_samples[i])
            for i in range(len(engine_samples)):
                res = engine.predict(engine_samples[i])
                latencies_ms.append(res["latency_ms"])

            p95_lat = float(np.percentile(latencies_ms, 95))
            mean_lat = float(np.mean(latencies_ms))

            metrics = {
                "pr_auc": float(eval_results["pr_auc"]),
                "roc_auc": float(eval_results["roc_auc"]),
                "f1_score": float(eval_results["f1_score"]),
                "precision": float(eval_results["precision"]),
                "recall": float(eval_results["recall"]),
                "inference_latency_p95_ms": p95_lat,
                "inference_latency_mean_ms": mean_lat,
            }

            # Log to experiment tracker
            run_ctx.log_params(
                {
                    "n_estimators": 150,
                    "learning_rate": 0.05,
                    "num_leaves": 31,
                    "scale_pos_weight": round(imbalance_ratio, 2),
                    "training_samples": len(X_train),
                    "fraud_count": int(y_train.sum()),
                }
            )
            run_ctx.log_metrics(metrics)
            run_ctx.log_artifact(str(candidate_path))

            logger.info(
                "Candidate model training and benchmark completed",
                extra={"pr_auc": metrics["pr_auc"], "latency_p95": p95_lat},
            )

        self.last_run_id = run_ctx.run_id
        return bundle, metrics, candidate_path

    def evaluate_and_deploy(
        self,
        candidate_path: Path,
        metrics: dict[str, float],
        gate_criteria: dict[str, float] | None = None,
        deploy: bool = True,
        run_id: str | None = None,
    ) -> tuple[ModelVersion, PromotionGateResult]:
        """Register candidate in ModelRegistry, evaluate promotion gates, and hot-swap production artifact."""
        candidate_run_id = run_id or getattr(self, "last_run_id", "retrain_run")

        # Register candidate in ModelRegistry
        version = self.registry.register_candidate(
            model_name=self.model_name,
            run_id=candidate_run_id,
            metrics=metrics,
            artifact_path=candidate_path,
            description="Continuous retraining candidate triggered by drift or schedule",
        )

        # Evaluate promotion gates and optionally deploy to production
        promoted_version, gate_result = self.registry.promote_to_production(
            model_name=self.model_name,
            version=version.version,
            deploy_to_artifacts=deploy,
            gates=gate_criteria,
        )

        return promoted_version, gate_result

    # Alias for API backwards compatibility
    evaluate_and_promote = evaluate_and_deploy

    def run_pipeline(
        self,
        baseline_df: pd.DataFrame | None = None,
        current_df: pd.DataFrame | None = None,
        force: bool = False,
        simulate_drift: bool = False,
        deploy: bool = True,
        gate_criteria: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Execute end-to-end continuous retraining workflow."""
        # 1. Dataset Acquisition
        if baseline_df is None:
            baseline_df = load_or_generate_dataset()

        if current_df is None:
            # Sample a recent batch from baseline
            sample_size = min(3000, len(baseline_df))
            current_df = (
                baseline_df.sample(n=sample_size, random_state=123).copy().reset_index(drop=True)
            )

            if simulate_drift:
                logger.info("Simulating severe data and concept drift...")
                current_df["amount"] = current_df["amount"] * 3.5 + np.random.uniform(
                    50, 150, len(current_df)
                )
                current_df["tx_count_10m"] = current_df["tx_count_10m"] + np.random.poisson(
                    3, len(current_df)
                )
                current_df["amount_to_avg_ratio"] = current_df["amount_to_avg_ratio"] * 2.8
                # Learnable shifted fraud pattern
                drifted_fraud = (current_df["amount"] > 500) & (
                    current_df["amount_to_avg_ratio"] > 3.0
                )
                current_df.loc[drifted_fraud, "is_fraud"] = 1

        # 2. Statistical Drift Detection
        drift_report, concept_info = self.detect_drift(
            baseline_df=baseline_df, current_df=current_df
        )
        drift_triggered = (
            drift_report.recommendation in ["RETRAINING_RECOMMENDED", "CRITICAL_DRIFT"]
            or drift_report.max_psi >= 0.25
            or concept_info.get("concept_drift_detected", False)
        )

        logger.info(
            "Drift evaluation finished",
            extra={
                "max_psi": drift_report.max_psi,
                "drift_features_count": len(drift_report.severe_drift_features),
                "recommendation": drift_report.recommendation,
                "retrain_triggered": drift_triggered or force,
            },
        )

        # 3. Decision Gate: Check whether retraining is warranted
        if not drift_triggered and not force:
            return {
                "retrained": False,
                "status": "SKIPPED_NO_DRIFT",
                "reason": "Feature distributions and concept targets remain stable within safety thresholds.",
                "drift_report": drift_report.to_dict(),
                "concept_drift": concept_info,
            }

        # 4. Training Candidate Model
        logger.info("Initiating candidate model training...")
        # Train on combined baseline and recent current data for continuous learning
        combined_train_df = pd.concat([baseline_df, current_df], ignore_index=True)
        bundle, metrics, candidate_path = self.train_candidate(train_df=combined_train_df)

        # 5. Registry Governance & Gate Evaluation
        version, gate_result = self.evaluate_and_promote(
            candidate_path=candidate_path,
            metrics=metrics,
            gate_criteria=gate_criteria,
            deploy=deploy,
        )

        return {
            "retrained": True,
            "status": "COMPLETED",
            "force_trigger": force,
            "drift_report": drift_report.to_dict(),
            "concept_drift": concept_info,
            "candidate_version": version.version,
            "candidate_stage": version.stage,
            "metrics": metrics,
            "gate_passed": gate_result.passed,
            "gate_details": gate_result.to_dict(),
            "deployed": gate_result.passed and deploy,
            "model_path": str(settings.MODEL_PATH)
            if (gate_result.passed and deploy)
            else str(candidate_path),
        }
