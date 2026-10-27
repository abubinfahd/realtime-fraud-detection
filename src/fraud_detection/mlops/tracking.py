"""MLOps Experiment Tracking & Artifact Management.

Integrates MLflow for logging runs, hyperparameters, precision-recall metrics,
confusion matrices, feature importances, and model bundles.

Supports:
- Remote or local MLflow Tracking Server (e.g., http://localhost:5000, sqlite:///mlruns.db)
- Robust local file-based store fallback (artifacts/mlruns/) when running offline
- Context manager workflow: `with tracker.start_run(run_name) as run:`
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from types import TracebackType
from typing import Any
import uuid

import joblib
import numpy as np

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger

logger = get_logger("fraud_detection.mlops.tracking")


class RunContext:
    """Active experiment run context for logging parameters, metrics, and artifacts."""

    def __init__(
        self,
        tracker: ExperimentTracker,
        run_id: str,
        run_name: str,
        experiment_id: str,
        start_time_iso: str,
        tags: dict[str, str] | None = None,
    ) -> None:
        self.tracker = tracker
        self.run_id = run_id
        self.run_name = run_name
        self.experiment_id = experiment_id
        self.start_time_iso = start_time_iso
        self.tags = tags or {}
        self.params: dict[str, Any] = {}
        self.metrics: dict[str, float] = {}
        self.status = "RUNNING"
        self._mlflow_run: Any = None

    def log_param(self, key: str, value: Any) -> None:
        """Record a single hyperparameter."""
        self.params[key] = value
        self.tracker._log_param(self, key, value)

    def log_params(self, params: dict[str, Any]) -> None:
        """Record multiple hyperparameters."""
        for k, v in params.items():
            self.log_param(k, v)

    def log_metric(self, key: str, value: float, step: int | None = None) -> None:
        """Record a performance metric."""
        float_val = float(value)
        self.metrics[key] = float_val
        self.tracker._log_metric(self, key, float_val, step)

    def log_metrics(self, metrics: dict[str, float], step: int | None = None) -> None:
        """Record multiple performance metrics."""
        for k, v in metrics.items():
            self.log_metric(k, v, step)

    def log_artifact(self, local_path: str | Path, artifact_path: str | None = None) -> None:
        """Attach a file artifact to the run."""
        self.tracker._log_artifact(self, Path(local_path), artifact_path)

    def log_dict(self, dictionary: dict[str, Any], artifact_file: str) -> None:
        """Serialize a Python dictionary as JSON and attach it to the run."""
        self.tracker._log_dict(self, dictionary, artifact_file)

    def log_model(
        self,
        model_bundle: dict[str, Any],
        artifact_name: str = "model_bundle.joblib",
    ) -> Path:
        """Persist serialized joblib model bundle and record it in run artifacts."""
        return self.tracker._log_model_bundle(self, model_bundle, artifact_name)

    def log_evaluation_plots(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        threshold: float = 0.50,
        feature_names: list[str] | None = None,
        feature_importances: np.ndarray | None = None,
    ) -> dict[str, str]:
        """Generate and attach confusion matrix, PR curve data, and feature rankings."""
        return self.tracker._log_evaluation_plots(
            self,
            y_true=y_true,
            y_prob=y_prob,
            threshold=threshold,
            feature_names=feature_names,
            feature_importances=feature_importances,
        )

    def __enter__(self) -> RunContext:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        status = "FAILED" if exc_type is not None else "FINISHED"
        self.tracker.end_run(status=status)


class ExperimentTracker:
    """Manages experiment lifecycle, tracking parameters, metrics, artifacts, and models."""

    def __init__(
        self,
        experiment_name: str = "fraud-detection-model",
        tracking_uri: str | None = None,
        local_store_dir: Path | str | None = None,
    ) -> None:
        self.experiment_name = experiment_name
        self.tracking_uri = tracking_uri or getattr(
            settings, "MLFLOW_TRACKING_URI", "file:./mlruns"
        )
        self.local_store_dir = Path(local_store_dir or "artifacts/mlruns") / self.experiment_name
        self.local_store_dir.mkdir(parents=True, exist_ok=True)

        self._active_run: RunContext | None = None
        self._mlflow: Any = None
        self._mlflow_enabled = False

        self._init_backend()

    @property
    def active_run(self) -> RunContext | None:
        """Return active RunContext if currently executing a run, else None."""
        return self._active_run

    def _init_backend(self) -> None:
        """Initialize MLflow client if available, otherwise prepare local structured store."""
        try:
            import mlflow

            self._mlflow = mlflow
            self._mlflow.set_tracking_uri(self.tracking_uri)
            self._mlflow.set_experiment(self.experiment_name)
            self._mlflow_enabled = True
            logger.info(
                "Connected to MLflow tracking engine",
                extra={"tracking_uri": self.tracking_uri, "experiment": self.experiment_name},
            )
        except Exception as exc:
            self._mlflow_enabled = False
            logger.info(
                "Running in local file-backed experiment tracking mode",
                extra={"local_dir": str(self.local_store_dir), "reason": str(exc)},
            )

    @property
    def is_mlflow_enabled(self) -> bool:
        """Return True if connected to live MLflow server or library."""
        return self._mlflow_enabled

    def start_run(
        self,
        run_name: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> RunContext:
        """Start a new experiment tracking run."""
        if self._active_run is not None:
            self.end_run(status="KILLED")

        run_id = uuid.uuid4().hex[:12]
        now_iso = datetime.now(UTC).isoformat()
        name = run_name or f"run-{run_id}"

        run_context = RunContext(
            tracker=self,
            run_id=run_id,
            run_name=name,
            experiment_id=self.experiment_name,
            start_time_iso=now_iso,
            tags=tags,
        )

        # Create local run directory
        run_dir = self.local_store_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(exist_ok=True)

        if self._mlflow_enabled and self._mlflow is not None:
            try:
                mlflow_run = self._mlflow.start_run(run_name=name, tags=tags)
                run_context._mlflow_run = mlflow_run
                run_context.run_id = mlflow_run.info.run_id
            except Exception as exc:
                logger.warning(
                    "MLflow start_run failed, falling back to local run context",
                    extra={"error": str(exc)},
                )

        self._active_run = run_context
        self._save_run_meta(run_context)
        print(f"[*] Started Experiment Run '{name}' [Run ID: {run_context.run_id}]")
        return run_context

    def end_run(self, status: str = "FINISHED") -> None:
        """Terminate active run and persist complete execution state."""
        if self._active_run is None:
            return

        run = self._active_run
        run.status = status
        self._save_run_meta(run)

        if self._mlflow_enabled and self._mlflow is not None and run._mlflow_run is not None:
            try:
                self._mlflow.end_run(status=status)
            except Exception as exc:
                logger.warning("Error ending MLflow run", extra={"error": str(exc)})

        print(f"[*] Finished Experiment Run '{run.run_name}' with status {status}")
        self._active_run = None

    def _save_run_meta(self, run: RunContext) -> None:
        """Write metadata JSON manifest for local run auditing."""
        run_dir = self.local_store_dir / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "run_id": run.run_id,
            "run_name": run.run_name,
            "experiment": self.experiment_name,
            "status": run.status,
            "start_time": run.start_time_iso,
            "end_time": datetime.now(UTC).isoformat() if run.status != "RUNNING" else None,
            "tags": run.tags,
            "params": run.params,
            "metrics": run.metrics,
        }
        with open(run_dir / "run_meta.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def _log_param(self, run: RunContext, key: str, value: Any) -> None:
        self._save_run_meta(run)
        if self._mlflow_enabled and self._mlflow is not None and run._mlflow_run is not None:
            try:
                self._mlflow.log_param(key, value)
            except Exception as exc:
                logger.debug("MLflow log_param skipped", extra={"error": str(exc)})

    def _log_metric(self, run: RunContext, key: str, value: float, step: int | None = None) -> None:
        self._save_run_meta(run)
        if self._mlflow_enabled and self._mlflow is not None and run._mlflow_run is not None:
            try:
                self._mlflow.log_metric(key, value, step=step)
            except Exception as exc:
                logger.debug("MLflow log_metric skipped", extra={"error": str(exc)})

    def _log_artifact(
        self, run: RunContext, local_path: Path, artifact_path: str | None = None
    ) -> None:
        if not local_path.exists():
            return
        dest_dir = self.local_store_dir / run.run_id / "artifacts"
        if artifact_path:
            dest_dir = dest_dir / artifact_path
        dest_dir.mkdir(parents=True, exist_ok=True)

        target_file = dest_dir / local_path.name
        if target_file.resolve() != local_path.resolve():
            import shutil

            shutil.copy2(local_path, target_file)

        if self._mlflow_enabled and self._mlflow is not None and run._mlflow_run is not None:
            try:
                self._mlflow.log_artifact(str(local_path), artifact_path=artifact_path)
            except Exception as exc:
                logger.debug("MLflow log_artifact skipped", extra={"error": str(exc)})

    def _log_dict(self, run: RunContext, dictionary: dict[str, Any], artifact_file: str) -> None:
        dest_file = self.local_store_dir / run.run_id / "artifacts" / artifact_file
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_file, "w", encoding="utf-8") as f:
            json.dump(dictionary, f, indent=2)

        if self._mlflow_enabled and self._mlflow is not None and run._mlflow_run is not None:
            try:
                self._mlflow.log_dict(dictionary, artifact_file)
            except Exception as exc:
                logger.debug("MLflow log_dict skipped", extra={"error": str(exc)})

    def _log_model_bundle(
        self,
        run: RunContext,
        model_bundle: dict[str, Any],
        artifact_name: str = "model_bundle.joblib",
    ) -> Path:
        model_path = self.local_store_dir / run.run_id / "artifacts" / artifact_name
        model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model_bundle, model_path, compress=3)

        if self._mlflow_enabled and self._mlflow is not None and run._mlflow_run is not None:
            try:
                self._mlflow.log_artifact(str(model_path), artifact_path="model")
            except Exception as exc:
                logger.debug("MLflow model artifact logging skipped", extra={"error": str(exc)})

        return model_path

    def _log_evaluation_plots(
        self,
        run: RunContext,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        threshold: float = 0.50,
        feature_names: list[str] | None = None,
        feature_importances: np.ndarray | None = None,
    ) -> dict[str, str]:
        """Compute and persist confusion matrix, PR curve metrics, and feature importances."""
        artifacts_dir = self.local_store_dir / run.run_id / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        y_pred = (y_prob >= threshold).astype(int)

        # 1. Confusion Matrix
        from sklearn.metrics import confusion_matrix

        cm = confusion_matrix(y_true, y_pred)
        tn, fp, fn, tp = int(cm[0, 0]), int(cm[0, 1]), int(cm[1, 0]), int(cm[1, 1])
        cm_dict = {
            "threshold": float(threshold),
            "true_negatives": tn,
            "false_positives": fp,
            "false_negatives": fn,
            "true_positives": tp,
            "matrix": cm.tolist(),
        }
        cm_path = artifacts_dir / "confusion_matrix.json"
        with open(cm_path, "w", encoding="utf-8") as f:
            json.dump(cm_dict, f, indent=2)

        # 2. Precision-Recall Curve points
        from sklearn.metrics import precision_recall_curve

        precisions, recalls, thresholds = precision_recall_curve(y_true, y_prob)
        # Downsample to 50 points for compact JSON
        step_idx = max(1, len(thresholds) // 50)
        pr_curve_data = {
            "recalls": [round(float(r), 4) for r in recalls[::step_idx]],
            "precisions": [round(float(p), 4) for p in precisions[::step_idx]],
            "thresholds": [round(float(t), 4) for t in thresholds[::step_idx]],
        }
        pr_path = artifacts_dir / "pr_curve.json"
        with open(pr_path, "w", encoding="utf-8") as f:
            json.dump(pr_curve_data, f, indent=2)

        # 3. Feature Importance Ranking
        feat_rank_dict: dict[str, float] = {}
        if feature_names is not None and feature_importances is not None:
            sorted_indices = np.argsort(feature_importances)[::-1]
            for idx in sorted_indices:
                feat_rank_dict[feature_names[idx]] = round(float(feature_importances[idx]), 4)
            feat_path = artifacts_dir / "feature_importance.json"
            with open(feat_path, "w", encoding="utf-8") as f:
                json.dump(feat_rank_dict, f, indent=2)

        # 4. Optional Matplotlib Plot Rendering (if matplotlib installed)
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            # PR Curve Plot
            plt.figure(figsize=(6, 4))
            plt.plot(recalls, precisions, color="#2563EB", lw=2, label="PR Curve")
            plt.xlabel("Recall")
            plt.ylabel("Precision")
            plt.title("Precision-Recall Curve")
            plt.grid(True, alpha=0.3)
            plt.legend(loc="lower left")
            plt.tight_layout()
            pr_png = artifacts_dir / "pr_curve.png"
            plt.savefig(pr_png, dpi=120)
            plt.close()

            # Feature Importance Bar Plot
            if feat_rank_dict:
                top_features = list(feat_rank_dict.keys())[:10][::-1]
                top_values = [feat_rank_dict[k] for k in top_features]
                plt.figure(figsize=(8, 5))
                plt.barh(top_features, top_values, color="#4F46E5")
                plt.xlabel("Importance")
                plt.title("Top 10 Feature Importances")
                plt.tight_layout()
                feat_png = artifacts_dir / "feature_importance.png"
                plt.savefig(feat_png, dpi=120)
                plt.close()

        except Exception as plot_err:
            logger.debug("Matplotlib plot rendering skipped", extra={"info": str(plot_err)})

        return {
            "confusion_matrix": str(cm_path),
            "pr_curve": str(pr_path),
        }

    def list_runs(self) -> list[dict[str, Any]]:
        """List all completed or active runs in local experiment store."""
        runs: list[dict[str, Any]] = []
        if not self.local_store_dir.exists():
            return runs

        for d in self.local_store_dir.iterdir():
            if d.is_dir():
                meta_file = d / "run_meta.json"
                if meta_file.exists():
                    try:
                        with open(meta_file, encoding="utf-8") as f:
                            runs.append(json.load(f))
                    except Exception:
                        pass
        runs.sort(key=lambda r: r.get("start_time", ""), reverse=True)
        return runs

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Fetch metadata for a specific run ID."""
        meta_file = self.local_store_dir / run_id / "run_meta.json"
        if meta_file.exists():
            with open(meta_file, encoding="utf-8") as f:
                return json.load(f)
        return None

    # Convenient alias for MLflow client compatibility
    search_runs = list_runs

    def get_latest_run(self) -> dict[str, Any] | None:
        """Retrieve most recently initiated run."""
        runs = self.list_runs()
        return runs[0] if runs else None
