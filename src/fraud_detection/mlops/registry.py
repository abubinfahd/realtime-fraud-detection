"""MLOps Model Registry & Automated Governance Gates.

Features:
- Programmatic model versioning and lifecycle stage management:
  (Development -> Staging -> Production -> Archived).
- Automated promotion gates validating PR-AUC, F1-Score, inference latency, and FPR.
- Integration with MLflow Model Registry (when MLflow is connected).
- Resilient local filesystem registry store (`artifacts/model_registry/`) with atomic transitions.
- Automatic archival of previous champion models when a new model is promoted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import Any

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger

logger = get_logger("fraud_detection.mlops.registry")

DEFAULT_PROMOTION_GATES = {
    "min_pr_auc": 0.850,
    "min_f1_score": 0.800,
    "max_inference_latency_ms": 3.0,
    "max_false_positive_rate": 0.05,
}


@dataclass
class ModelVersion:
    """Represents a registered model artifact and its lineage metadata."""

    name: str
    version: int
    run_id: str
    stage: str  # "Development" | "Staging" | "Production" | "Archived"
    metrics: dict[str, float]
    artifact_path: str
    created_at: str
    promoted_at: str | None = None
    tags: dict[str, str] | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize version metadata to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelVersion:
        """Instantiate ModelVersion from dictionary."""
        return cls(
            name=data["name"],
            version=data["version"],
            run_id=data["run_id"],
            stage=data.get("stage", "Development"),
            metrics=data.get("metrics", {}),
            artifact_path=data.get("artifact_path", ""),
            created_at=data.get("created_at", datetime.now(UTC).isoformat()),
            promoted_at=data.get("promoted_at"),
            tags=data.get("tags"),
            description=data.get("description", ""),
        )


@dataclass
class PromotionGateResult:
    """Outcome of quality evaluation gates against candidate model metrics."""

    passed: bool
    model_name: str
    version: int
    evaluations: dict[str, dict[str, Any]]
    failure_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to dictionary."""
        return asdict(self)


class ModelRegistry:
    """Automated Model Governance and Promotion Registry."""

    def __init__(
        self,
        registry_dir: Path | str | None = None,
        gates: dict[str, float] | None = None,
        production_model_path: Path | str | None = None,
    ) -> None:
        self.registry_dir = Path(registry_dir or "artifacts/model_registry")
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.gates = gates or dict(DEFAULT_PROMOTION_GATES)
        self.production_model_path = Path(
            production_model_path or getattr(settings, "MODEL_PATH", "artifacts/fraud_model.joblib")
        )

        self._mlflow_client: Any = None
        self._mlflow_enabled = False
        self._init_backend()

    def _init_backend(self) -> None:
        """Connect to MLflow client if available, else use local registry directory."""
        try:
            from mlflow.tracking import MlflowClient

            self._mlflow_client = MlflowClient()
            self._mlflow_enabled = True
            logger.info("Connected to MLflow Model Registry client")
        except Exception as exc:
            self._mlflow_enabled = False
            logger.info(
                "Running in local filesystem Model Registry mode",
                extra={"registry_dir": str(self.registry_dir), "reason": str(exc)},
            )

    def _get_manifest_path(self, model_name: str) -> Path:
        """Get path to the local model registry metadata manifest."""
        model_dir = self.registry_dir / model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        return model_dir / "registry.json"

    def _load_manifest(self, model_name: str) -> dict[str, Any]:
        """Load registered versions manifest for model."""
        path = self._get_manifest_path(model_name)
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"name": model_name, "latest_version": 0, "versions": []}

    def _save_manifest(self, model_name: str, data: dict[str, Any]) -> None:
        """Atomically persist registered versions manifest."""
        path = self._get_manifest_path(model_name)
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        shutil.move(str(temp_path), str(path))

    def register_candidate(
        self,
        model_name: str,
        run_id: str,
        metrics: dict[str, float],
        artifact_path: str | Path,
        tags: dict[str, str] | None = None,
        description: str = "",
    ) -> ModelVersion:
        """
        Register a newly trained model candidate into the registry (Stage: Development).

        Parameters
        ----------
        model_name : str
            Canonical model identifier (e.g. 'fraud-detector').
        run_id : str
            Lineage experiment run ID where model was produced.
        metrics : dict[str, float]
            Validation evaluation metrics (pr_auc, f1_score, latency, fpr).
        artifact_path : str | Path
            Filesystem location of serialized model (.joblib).
        tags : dict[str, str] | None
            Descriptive key-value tags.
        description : str
            Release notes or training context.
        """
        manifest = self._load_manifest(model_name)
        next_ver = manifest.get("latest_version", 0) + 1

        # Copy artifact to versioned registry directory
        dest_dir = self.registry_dir / model_name / f"v{next_ver}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        src_path = Path(artifact_path)
        persisted_artifact = dest_dir / src_path.name
        if src_path.exists() and src_path.resolve() != persisted_artifact.resolve():
            shutil.copy2(src_path, persisted_artifact)

        version = ModelVersion(
            name=model_name,
            version=next_ver,
            run_id=run_id,
            stage="Development",
            metrics={k: float(v) for k, v in metrics.items()},
            artifact_path=str(persisted_artifact),
            created_at=datetime.now(UTC).isoformat(),
            tags=tags or {},
            description=description,
        )

        manifest["latest_version"] = next_ver
        manifest["versions"].append(version.to_dict())
        self._save_manifest(model_name, manifest)

        # MLflow Model Registry synchronization (if active)
        if self._mlflow_enabled and self._mlflow_client is not None:
            try:
                self._mlflow_client.create_registered_model(model_name)
            except Exception:
                pass
            try:
                self._mlflow_client.create_model_version(
                    name=model_name,
                    source=str(persisted_artifact),
                    run_id=run_id,
                    tags=tags,
                    description=description,
                )
            except Exception as exc:
                logger.debug("MLflow create_model_version skipped", extra={"error": str(exc)})

        print(f"[*] Registered model '{model_name}' version {next_ver} [Stage: Development]")
        return version

    def evaluate_gates(
        self,
        candidate: ModelVersion,
        gates: dict[str, float] | None = None,
    ) -> PromotionGateResult:
        """
        Evaluate candidate against strict automated production deployment criteria.

        Criteria:
        - min_pr_auc: e.g. >= 0.850
        - min_f1_score: e.g. >= 0.800
        - max_inference_latency_ms: e.g. <= 3.0 ms
        - max_false_positive_rate: e.g. <= 0.05
        """
        active_gates = gates or self.gates
        evaluations: dict[str, dict[str, Any]] = {}
        failure_reasons: list[str] = []
        metrics = candidate.metrics

        # 1. PR-AUC gate
        if "min_pr_auc" in active_gates:
            target = active_gates["min_pr_auc"]
            actual = float(metrics.get("pr_auc", 0.0))
            passed = actual >= target
            evaluations["pr_auc"] = {
                "target": target,
                "actual": actual,
                "criterion": f">= {target}",
                "passed": passed,
            }
            if not passed:
                failure_reasons.append(
                    f"PR-AUC {actual:.4f} is below minimum requirement {target:.4f}"
                )

        # 2. F1-Score gate
        if "min_f1_score" in active_gates:
            target = active_gates["min_f1_score"]
            actual = float(metrics.get("f1_score", 0.0))
            passed = actual >= target
            evaluations["f1_score"] = {
                "target": target,
                "actual": actual,
                "criterion": f">= {target}",
                "passed": passed,
            }
            if not passed:
                failure_reasons.append(
                    f"F1-Score {actual:.4f} is below minimum requirement {target:.4f}"
                )

        # 3. Latency gate
        if "max_inference_latency_ms" in active_gates:
            target = active_gates["max_inference_latency_ms"]
            actual = float(
                metrics.get(
                    "inference_latency_p95_ms",
                    metrics.get("inference_latency_mean_ms", metrics.get("latency_ms", 1.0)),
                )
            )
            passed = actual <= target
            evaluations["latency_ms"] = {
                "target": target,
                "actual": actual,
                "criterion": f"<= {target} ms",
                "passed": passed,
            }
            if not passed:
                failure_reasons.append(
                    f"Inference latency {actual:.2f} ms exceeds SLA target of {target:.2f} ms"
                )

        # 4. False Positive Rate (FPR) gate
        if "max_false_positive_rate" in active_gates:
            target = active_gates["max_false_positive_rate"]
            actual = float(metrics.get("fpr", metrics.get("false_positive_rate", 0.02)))
            passed = actual <= target
            evaluations["fpr"] = {
                "target": target,
                "actual": actual,
                "criterion": f"<= {target}",
                "passed": passed,
            }
            if not passed:
                failure_reasons.append(f"FPR {actual:.4f} exceeds safety threshold {target:.4f}")

        overall_passed = len(failure_reasons) == 0

        return PromotionGateResult(
            passed=overall_passed,
            model_name=candidate.name,
            version=candidate.version,
            evaluations=evaluations,
            failure_reasons=failure_reasons,
        )

    def promote_to_production(
        self,
        model_name: str,
        version: int,
        force: bool = False,
        deploy_to_artifacts: bool = True,
        gates: dict[str, float] | None = None,
    ) -> tuple[ModelVersion, PromotionGateResult]:
        """
        Evaluate candidate and atomically promote it to Production stage.

        Also archives the existing Production model and optionally copies the
        champion artifact to artifacts/fraud_model.joblib for live inference serving.
        """
        candidate = self.get_model_version(model_name, version)
        if candidate is None:
            raise ValueError(f"Model '{model_name}' version {version} not found in registry.")

        gate_result = self.evaluate_gates(candidate, gates=gates)

        if not gate_result.passed and not force:
            reasons_str = "; ".join(gate_result.failure_reasons)
            print(f"[FAIL] Model {model_name} v{version} failed promotion gates: {reasons_str}")
            return candidate, gate_result

        # Load manifest to execute atomic transition
        manifest = self._load_manifest(model_name)
        now_iso = datetime.now(UTC).isoformat()
        promoted_obj: ModelVersion | None = None

        for item in manifest["versions"]:
            # Demote existing Production model to Archived
            if item["stage"] == "Production" and item["version"] != version:
                item["stage"] = "Archived"
                print(f"[*] Demoting previous champion v{item['version']} to [Stage: Archived]")

            # Promote candidate to Production
            if item["version"] == version:
                item["stage"] = "Production"
                item["promoted_at"] = now_iso
                promoted_obj = ModelVersion.from_dict(item)

        if promoted_obj is None:
            raise RuntimeError(f"Candidate v{version} could not be updated in manifest.")

        self._save_manifest(model_name, manifest)

        # Deploy champion artifact directly to production serving path
        if deploy_to_artifacts:
            src_artifact = Path(promoted_obj.artifact_path)
            dest_prod = self.production_model_path
            if src_artifact.exists() and src_artifact.resolve() != dest_prod.resolve():
                dest_prod.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_artifact, dest_prod)
                print(f"[PASS] Champion artifact deployed to production serving path: {dest_prod}")

        # MLflow Model Registry alias / stage update
        if self._mlflow_enabled and self._mlflow_client is not None:
            try:
                self._mlflow_client.set_registered_model_alias(
                    name=model_name,
                    alias="Production",
                    version=str(version),
                )
            except Exception as exc:
                logger.debug("MLflow alias update skipped", extra={"error": str(exc)})

        print(
            f"[PASS] Model '{model_name}' version {version} successfully promoted to [Stage: Production]!"
        )
        return promoted_obj, gate_result

    def get_production_model(self, model_name: str) -> ModelVersion | None:
        """Fetch current active Production champion model."""
        manifest = self._load_manifest(model_name)
        for item in manifest.get("versions", []):
            if item.get("stage") == "Production":
                return ModelVersion.from_dict(item)
        return None

    def get_model_version(self, model_name: str, version: int) -> ModelVersion | None:
        """Retrieve metadata for a specific model version."""
        manifest = self._load_manifest(model_name)
        for item in manifest.get("versions", []):
            if item.get("version") == version:
                return ModelVersion.from_dict(item)
        return None

    def list_versions(self, model_name: str) -> list[ModelVersion]:
        """List all registered versions sorted by version number descending."""
        manifest = self._load_manifest(model_name)
        versions = [ModelVersion.from_dict(item) for item in manifest.get("versions", [])]
        versions.sort(key=lambda v: v.version, reverse=True)
        return versions

    def archive_version(self, model_name: str, version: int) -> ModelVersion:
        """Manually transition a model version to Archived stage."""
        manifest = self._load_manifest(model_name)
        updated_obj: ModelVersion | None = None
        for item in manifest.get("versions", []):
            if item.get("version") == version:
                item["stage"] = "Archived"
                updated_obj = ModelVersion.from_dict(item)
        if updated_obj is None:
            raise ValueError(f"Model '{model_name}' version {version} not found.")

        self._save_manifest(model_name, manifest)
        return updated_obj

    # Convenient aliases for API backwards compatibility
    get_version_history = list_versions
    get_champion = get_production_model
