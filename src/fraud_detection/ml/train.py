"""
Offline ML Model Training, Evaluation & Serialization Pipeline.

Orchestrates data generation, stratified splitting, model fitting
(LightGBM + Isolation Forest), PR-AUC evaluation, threshold optimization,
artifact serialization, and CPU inference latency benchmarking.
"""

import os
import warnings
from datetime import UTC, datetime
from typing import Any

import joblib
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger
from fraud_detection.ml.data_loader import load_or_generate_dataset
from fraud_detection.ml.evaluate import evaluate_classifier, find_optimal_f1_threshold
from fraud_detection.ml.features import FEATURE_NAMES
from fraud_detection.ml.preprocessing import preprocess_dataframe

logger = get_logger(__name__)
warnings.filterwarnings("ignore", category=UserWarning)
RANDOM_SEED: int = 42


def train_and_evaluate() -> dict[str, Any]:
    """Train LightGBM + Isolation Forest, evaluate PR-AUC, serialize model, and benchmark."""
    print("=" * 70)
    print("Stage 3: Offline ML Model Training & Serialization Pipeline")
    print("=" * 70)

    # 1. Dataset Loading (loads data/raw/transactions_10k.csv or generates it)
    print(f"[*] Loading transaction dataset from {settings.DEMO_DATA_PATH}...")
    df = load_or_generate_dataset()
    X, y = preprocess_dataframe(df)

    # 2. Stratified Train / Validation / Test Split (70% / 15% / 15%)
    X_train_val, X_test, y_train_val, y_test = train_test_split(
        X, y, test_size=0.15, stratify=y, random_state=RANDOM_SEED
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_train_val, y_train_val, test_size=0.17647, stratify=y_train_val, random_state=RANDOM_SEED
    )

    print("[*] Dataset split summary:")
    print(
        f"    - Training:   {len(X_train):,} samples (Fraud: {y_train.sum()} | {y_train.mean():.2%})"
    )
    print(f"    - Validation: {len(X_val):,} samples (Fraud: {y_val.sum()} | {y_val.mean():.2%})")
    print(
        f"    - Holdout:    {len(X_test):,} samples (Fraud: {y_test.sum()} | {y_test.mean():.2%})"
    )

    # 3. Supervised Model: LightGBM with Imbalance Handling
    imbalance_ratio = float((len(y_train) - y_train.sum()) / max(y_train.sum(), 1))
    print(
        f"[*] Class imbalance ratio: {imbalance_ratio:.1f}:1. Setting scale_pos_weight={imbalance_ratio:.1f}"
    )

    lgb_model = LGBMClassifier(
        objective="binary",
        boosting_type="gbdt",
        n_estimators=150,
        learning_rate=0.05,
        num_leaves=31,
        max_depth=6,
        scale_pos_weight=imbalance_ratio,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=RANDOM_SEED,
        n_jobs=-1,
        verbose=-1,
    )

    # Convert DataFrame to contiguous float64 NumPy arrays to eliminate feature name warnings
    # and achieve zero-overhead single-event inference
    X_tr_arr = np.ascontiguousarray(X_train.values, dtype=np.float64)
    X_va_arr = np.ascontiguousarray(X_val.values, dtype=np.float64)
    X_te_arr = np.ascontiguousarray(X_test.values, dtype=np.float64)

    print("[*] Training Supervised LightGBM classifier...")
    lgb_model.fit(
        X_tr_arr,
        y_train,
        eval_set=[(X_va_arr, y_val)],
    )

    # 4. Unsupervised Model: Isolation Forest
    print("[*] Training Unsupervised Isolation Forest (Anomaly Detector)...")
    iso_forest = IsolationForest(
        n_estimators=100,
        contamination=0.01,
        max_samples="auto",
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    iso_forest.fit(X_tr_arr)

    # Configure estimators to single-threaded CPU mode for sub-millisecond per-sample inference
    # (eliminates joblib/OpenMP multi-core thread lock overhead on 1-row streaming predictions)
    lgb_model.set_params(n_jobs=1)
    iso_forest.set_params(n_jobs=1)

    # 5. Threshold Optimization & Evaluation
    print("\n" + "=" * 70)
    print("Holdout Test Set Performance & Metrics Analysis")
    print("=" * 70)

    val_probs = lgb_model.predict_proba(X_va_arr)[:, 1]
    optimal_th = find_optimal_f1_threshold(y_val, val_probs)

    test_probs = lgb_model.predict_proba(X_te_arr)[:, 1]
    eval_results = evaluate_classifier(y_test, test_probs, threshold=optimal_th)

    cm = eval_results["confusion_matrix"]
    tn, fp, fn, tp = (
        cm["true_negatives"],
        cm["false_positives"],
        cm["false_negatives"],
        cm["true_positives"],
    )

    print("[*] Primary Evaluation Metric:")
    print(f"    - PR-AUC (Precision-Recall Area Under Curve): {eval_results['pr_auc']:.4f}")
    print(f"    - ROC-AUC:                                    {eval_results['roc_auc']:.4f}")
    print(f"[*] Optimal Decision Threshold (Max F1):          {optimal_th:.4f}")
    print(f"    - Precision at Threshold:                     {eval_results['precision']:.2%}")
    print(f"    - Recall at Threshold:                        {eval_results['recall']:.2%}")
    print(f"    - F1-Score:                                   {eval_results['f1_score']:.4f}")
    print(f"[*] Confusion Matrix (Test Set: {len(y_test):,} transactions):")
    print(f"    - True Negatives  (Legitimate Approved):      {tn:,}")
    print(f"    - False Positives (Legitimate Flagged/Review):{fp:,}")
    print(f"    - False Negatives (Missed Fraud):             {fn:,}")
    print(f"    - True Positives  (Caught Fraud):             {tp:,}")

    # Why Accuracy is Deceptive
    raw_accuracy = (tn + tp) / len(y_test)
    dummy_accuracy = (len(y_test) - y_test.sum()) / len(y_test)
    print("\n[!] Critical Engineering Note on Raw Accuracy:")
    print(f"    - Raw Accuracy achieved: {raw_accuracy:.2%}")
    print(f"    - Dummy Baseline (Predict All 0): {dummy_accuracy:.2%}")
    print(
        f"    -> Raw Accuracy is misleading because a dummy model achieving {dummy_accuracy:.2%} catches 0 fraud."
    )
    print(
        f"    -> PR-AUC ({eval_results['pr_auc']:.4f}) correctly verifies minority class detection efficiency."
    )

    # 6. Serialization
    settings.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {
        "version": "1.0.0",
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

    print(f"\n[*] Serializing trained artifact to {settings.MODEL_PATH}...")
    joblib.dump(bundle, settings.MODEL_PATH, compress=3)
    file_size_kb = os.path.getsize(settings.MODEL_PATH) / 1024
    print(f"[+] Artifact serialized successfully ({file_size_kb:.1f} KB).")

    # 7. CPU Inference Latency Benchmark
    benchmark_count = min(len(X_test), 5000)
    print("\n" + "=" * 70)
    print(f"CPU Inference Latency Benchmark ({benchmark_count:,} Transactions)")
    print("=" * 70)

    from fraud_detection.ml.inference import InferenceEngine

    engine = InferenceEngine(model_path=settings.MODEL_PATH)
    benchmark_samples = X_test.iloc[:benchmark_count].values

    latencies_ms: list[float] = []

    # Warm-up (100 samples)
    for i in range(100):
        _ = engine.predict(benchmark_samples[i])

    # Timed inference per individual transaction
    for i in range(len(benchmark_samples)):
        res = engine.predict(benchmark_samples[i])
        latencies_ms.append(res["latency_ms"])

    mean_lat = float(np.mean(latencies_ms))
    p50_lat = float(np.percentile(latencies_ms, 50))
    p95_lat = float(np.percentile(latencies_ms, 95))
    p99_lat = float(np.percentile(latencies_ms, 99))
    throughput_rps = 1000.0 / max(mean_lat, 0.001)

    print("[*] Benchmark Results (Single-Threaded CPU):")
    print(f"    - Mean Latency:  {mean_lat:.3f} ms")
    print(f"    - P50 Latency:   {p50_lat:.3f} ms")
    print(f"    - P95 Latency:   {p95_lat:.3f} ms")
    print(f"    - P99 Latency:   {p99_lat:.3f} ms")
    print(f"    - Throughput:    ~{throughput_rps:,.0f} predictions/sec / CPU core")

    if p95_lat < 3.0:
        print("[+] PASS: P95 CPU inference latency is well within < 3.0 ms budget!")
    else:
        print("[!] WARNING: P95 latency exceeds 3.0 ms target.")

    print("=" * 70)
    print("Stage 3 Completed Successfully.")
    print("=" * 70)

    return bundle


def main() -> None:
    """CLI script entrypoint."""
    train_and_evaluate()


if __name__ == "__main__":
    main()
