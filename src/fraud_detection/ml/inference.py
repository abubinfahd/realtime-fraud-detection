"""
Real-time in-process CPU inference engine.

Loads serialized model bundles (LightGBM + Isolation Forest) and evaluates
feature vectors with sub-millisecond execution latency.
"""

import time
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.ml.features import FEATURE_NAMES, extract_features

logger = get_logger(__name__)
warnings.filterwarnings("ignore", category=UserWarning)


class InferenceEngine:
    """Thread-safe in-memory inference wrapper for hybrid fraud scoring."""

    def __init__(self, model_path: Path | str | None = None) -> None:
        self.model_path = Path(model_path or settings.MODEL_PATH)
        self.bundle: dict[str, Any] = {}
        self.lgb_model: Any = None
        self.iso_forest: Any = None
        self.thresholds: dict[str, float] = {}
        self.feature_names: list[str] = []
        self._load_bundle()

    def _load_bundle(self) -> None:
        """Load and unpack the serialized model artifact."""
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Model bundle not found at {self.model_path}. "
                "Execute 'uv run fraud-train' or 'uv run python -m fraud_detection.ml.train' first."
            )

        logger.info("Loading model bundle", extra={"path": str(self.model_path)})
        self.bundle = joblib.load(self.model_path)
        self.lgb_model = self.bundle["supervised_model"]
        self.iso_forest = self.bundle["unsupervised_model"]
        self.thresholds = self.bundle.get("thresholds", {})
        self.feature_names = self.bundle.get("feature_names", [])

        # Enforce single-threaded mode to eliminate thread synchronization overhead on 1-row inputs
        if hasattr(self.lgb_model, "set_params"):
            self.lgb_model.set_params(n_jobs=1)
        if hasattr(self.iso_forest, "set_params"):
            self.iso_forest.set_params(n_jobs=1)

        # Precompute Isolation Forest node depths for zero-overhead C-extension traversal (< 1 ms latency)
        self._init_fast_isolation_forest()

    def _init_fast_isolation_forest(self) -> None:
        """Precompute node depths for Isolation Forest to bypass SciPy CSR matrix allocation."""
        if not hasattr(self.iso_forest, "estimators_"):
            self._fast_iso_ready = False
            return

        def _euler_c(n: int) -> float:
            if n > 2:
                return 2.0 * (np.log(n - 1) + 0.5772156649) - (2.0 * (n - 1) / n)
            elif n == 2:
                return 1.0
            return 0.0

        self._iso_precomputed: list[np.ndarray] = []
        for tree in self.iso_forest.estimators_:
            node_count = tree.tree_.node_count
            depths = np.zeros(node_count, dtype=np.float64)
            c_left = tree.tree_.children_left
            c_right = tree.tree_.children_right
            stack = [(0, 0)]
            while stack:
                nid, d = stack.pop()
                depths[nid] = d
                if c_left[nid] != -1:
                    stack.append((c_left[nid], d + 1))
                if c_right[nid] != -1:
                    stack.append((c_right[nid], d + 1))
            n_samples = tree.tree_.n_node_samples
            leaf_c = np.array([_euler_c(int(n)) for n in n_samples], dtype=np.float64)
            self._iso_precomputed.append(depths + leaf_c)

        self._iso_c_factor = float(_euler_c(self.iso_forest.max_samples_))
        self._iso_offset = float(self.iso_forest.offset_)
        self._fast_iso_ready = True

    def predict(self, feature_vector: np.ndarray) -> dict[str, Any]:
        """
        Execute hybrid scoring on a 1D or 2D feature array.

        Parameters
        ----------
        feature_vector : np.ndarray
            Shape (10,) or (1, 10) float array conforming to FEATURE_NAMES.

        Returns
        -------
        dict[str, Any]
            Fraud probability, anomaly score, composite risk score, decision, and latency.
        """
        t0 = time.perf_counter()

        if isinstance(feature_vector, np.ndarray):
            X = feature_vector.reshape(1, -1) if feature_vector.ndim == 1 else feature_vector
        else:
            X = np.asarray(feature_vector, dtype=np.float64).reshape(1, -1)

        X = np.ascontiguousarray(X, dtype=np.float64)

        # 1. Supervised Fraud Probability (LightGBM)
        fraud_prob = float(self.lgb_model.predict_proba(X)[0, 1])

        # 2. Unsupervised Anomaly Score (Fast Isolation Forest evaluation)
        if getattr(self, "_fast_iso_ready", False):
            X_f32 = X.astype(np.float32)
            leaves = [
                p[t.tree_.apply(X_f32)[0]]
                for t, p in zip(self.iso_forest.estimators_, self._iso_precomputed)
            ]
            mean_depth = sum(leaves) / len(leaves)
            raw_anomaly = float(-(2.0 ** (-mean_depth / self._iso_c_factor)) - self._iso_offset)
        else:
            raw_anomaly = float(self.iso_forest.decision_function(X)[0])

        # Sigmoid normalization: maps negative outliers closer to 1.0
        anomaly_score = float(1.0 / (1.0 + np.exp(raw_anomaly * 4.0)))

        # 3. Composite Risk Score (Weighted blend: 65% LightGBM, 35% Isolation Forest)
        composite_risk = float(np.clip(0.65 * fraud_prob + 0.35 * anomaly_score, 0.0, 1.0))

        # 4. Decision Threshold Mapping
        low_th = self.thresholds.get("fraud_low", settings.FRAUD_THRESHOLD_LOW)
        high_th = self.thresholds.get("fraud_high", settings.FRAUD_THRESHOLD_HIGH)

        if composite_risk >= high_th:
            status = "REJECTED"
        elif composite_risk >= low_th:
            status = "FLAGGED"
        else:
            status = "APPROVED"

        latency_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "fraud_probability": round(fraud_prob, 4),
            "anomaly_score": round(anomaly_score, 4),
            "risk_score": round(composite_risk, 4),
            "status": status,
            "latency_ms": round(latency_ms, 3),
        }

    def score_transaction(
        self,
        transaction: Mapping[str, Any],
        velocity: Mapping[str, Any] | None = None,
        rule_result: Any | None = None,
    ) -> dict[str, Any]:
        """
        Execute unified scoring on a single transaction dictionary.

        Integrates feature extraction, ML inference, and deterministic rule overrides.
        """
        t0 = time.perf_counter()
        feat_vec = extract_features(transaction, velocity)
        pred = self.predict(feat_vec)

        fraud_prob = pred["fraud_probability"]
        anomaly_score = pred["anomaly_score"]
        raw_risk = pred["risk_score"]
        model_status = pred["status"]

        # Rule penalty & override handling
        rule_violations = []
        reasons = []
        override_verdict = None
        rule_penalty = 0.0

        if rule_result is not None:
            rule_violations = [v.rule_code for v in getattr(rule_result, "violations", [])]
            reasons = list(getattr(rule_result, "reasons", []))
            override_verdict = getattr(rule_result, "override_verdict", None)
            rule_penalty = float(getattr(rule_result, "total_penalty", 0.0))

        # Composite score calculation with rule penalties
        composite_risk = float(np.clip(raw_risk + rule_penalty, 0.0, 1.0))

        # Determine final status with rule overrides
        tx_count_1m = int((velocity or {}).get("tx_count_1m", 1))
        if override_verdict == "REJECTED":
            final_status = "REJECTED"
            composite_risk = 1.0
        elif override_verdict == "FLAGGED":
            final_status = "FLAGGED"
            composite_risk = round(float(np.clip(max(composite_risk, 0.50), 0.50, 0.74)), 4)
        elif (
            not rule_violations
            and model_status == "REJECTED"
            and float(transaction.get("amount", 0.0)) < 5000.0
            and tx_count_1m < 4
        ):
            # Single-event ML anomaly without deterministic hard-block rule -> 2FA / Manual Review
            final_status = "FLAGGED"
            composite_risk = round(float(np.clip(composite_risk, 0.55, 0.74)), 4)
        else:
            final_status = model_status

        latency_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "transaction_id": str(transaction.get("transaction_id", "")),
            "user_id": str(transaction.get("user_id", "")),
            "account_id": str(transaction.get("account_id", "")),
            "amount": float(transaction.get("amount", 0.0)),
            "currency": str(transaction.get("currency", "USD")),
            "merchant_name": str(transaction.get("merchant_name", "Unknown")),
            "merchant_category": str(transaction.get("merchant_category", "retail")),
            "fraud_probability": round(fraud_prob, 4),
            "anomaly_score": round(anomaly_score, 4),
            "risk_score": round(composite_risk, 4),
            "status": final_status,
            "rule_violations": rule_violations,
            "reasons": reasons,
            "latency_ms": round(latency_ms, 3),
            "features": {name: float(val) for name, val in zip(FEATURE_NAMES, feat_vec)},
        }


def run_demo_inference(
    csv_path: Path | str | None = None,
    model_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """
    Execute batch inference on the demo 10-transaction dataset using the saved model.
    Prints a rich evaluation summary table to the console.
    """
    import pandas as pd

    from fraud_detection.ml.preprocessing import preprocess_dataframe

    path = Path(csv_path or settings.DEMO_INFERENCE_DATA_PATH)
    if not path.exists():
        fallback = settings.DATA_DIR / "demo_inference_10.csv"
        if fallback.exists():
            path = fallback
        else:
            raise FileNotFoundError(f"Inference demo CSV not found at {path}")

    print("=" * 105)
    print("Real-Time Fraud Detection — Saved Model Inference Demonstration")
    print(f"Data Source: {path}")
    print(f"Model Path:  {model_path or settings.MODEL_PATH}")
    print("=" * 105)

    df = pd.read_csv(path)
    X, y_true = preprocess_dataframe(df)

    engine = InferenceEngine(model_path=model_path)

    # Warm up engine (10 passes)
    for _ in range(10):
        _ = engine.predict(X.iloc[0].values)

    results: list[dict[str, Any]] = []

    print(
        f"{'#':<3} | {'TX ID':<22} | {'Merchant':<16} | {'Amount':<8} | "
        f"{'P(Fraud)':<8} | {'Anomaly':<8} | {'Risk':<6} | {'Verdict':<9} | {'Latency'}"
    )
    print("-" * 105)

    for i in range(len(df)):
        row = df.iloc[i]
        feat_vec = X.iloc[i].values
        pred = engine.predict(feat_vec)

        tx_id = str(row["transaction_id"])
        merchant = str(row.get("merchant_name", row.get("merchant_category", "Unknown")))[:16]
        amount = f"${float(row['amount']):.2f}"
        p_fraud = f"{pred['fraud_probability']:.4f}"
        anomaly = f"{pred['anomaly_score']:.4f}"
        risk = f"{pred['risk_score']:.2f}"
        status = pred["status"]
        lat = f"{pred['latency_ms']:.2f} ms"

        print(
            f"{i + 1:<3} | {tx_id:<22} | {merchant:<16} | {amount:<8} | "
            f"{p_fraud:<8} | {anomaly:<8} | {risk:<6} | {status:<9} | {lat}"
        )

        results.append(
            {
                "transaction_id": tx_id,
                "merchant": merchant,
                "amount": float(row["amount"]),
                "is_fraud_ground_truth": int(y_true[i]),
                **pred,
            }
        )

    latencies = [r["latency_ms"] for r in results]
    print("-" * 105)
    print(f"[*] Total Evaluated: {len(results)} transactions")
    print(f"[*] Mean Latency:    {np.mean(latencies):.2f} ms per transaction")
    print(f"[*] P95 Latency:     {np.percentile(latencies, 95):.2f} ms")
    print(
        f"[*] Verdict Breakdown: "
        f"{sum(1 for r in results if r['status'] == 'APPROVED')} APPROVED | "
        f"{sum(1 for r in results if r['status'] == 'FLAGGED')} FLAGGED | "
        f"{sum(1 for r in results if r['status'] == 'REJECTED')} REJECTED"
    )
    print("=" * 105)

    return results


def main() -> None:
    """CLI entrypoint for fraud-infer."""
    run_demo_inference()


if __name__ == "__main__":
    main()
