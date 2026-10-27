#!/usr/bin/env python
"""
MLOps Continuous Retraining CLI Runner.

Executes continuous retraining triggered by statistical data drift (PSI / KS-test)
or on a regular maintenance schedule.

Usage:
    # Run drift check and trigger retraining if drift is detected
    python scripts/run_retraining.py

    # Simulate production data drift to test automated retraining trigger
    python scripts/run_retraining.py --simulate-drift

    # Force retraining regardless of drift metrics
    python scripts/run_retraining.py --force

    # Dry-run: Evaluate drift without deploying new artifact
    python scripts/run_retraining.py --dry-run
"""

import argparse
import sys
import time

from fraud_detection.mlops.pipeline import RetrainingPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MLOps Continuous Retraining Pipeline Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force retraining regardless of drift detection results.",
    )
    parser.add_argument(
        "--simulate-drift",
        action="store_true",
        help="Simulate severe data and concept drift to test trigger logic.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run drift check and candidate evaluation without deploying model.",
    )
    parser.add_argument(
        "--experiment-name",
        type=str,
        default="fraud-detection-production",
        help="Name of MLflow / local tracking experiment.",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="fraud-detector",
        help="Name of model in Model Registry.",
    )
    return parser.parse_args()


def print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main() -> None:
    args = parse_args()
    print_header("MLOps Continuous Retraining Engine (Stage 11)")
    print("[*] Configuration:")
    print(f"    - Force Retraining:   {args.force}")
    print(f"    - Simulate Drift:     {args.simulate_drift}")
    print(f"    - Dry Run (No Deploy):{args.dry_run}")
    print(f"    - Experiment Name:    {args.experiment_name}")
    print(f"    - Model Name:         {args.model_name}")

    start_time = time.perf_counter()
    pipeline = RetrainingPipeline(model_name=args.model_name)

    print("\n[*] Step 1: Evaluating Statistical Data & Concept Drift...")
    result = pipeline.run_pipeline(
        force=args.force,
        simulate_drift=args.simulate_drift,
        deploy=not args.dry_run,
    )

    drift_report = result.get("drift_report", {})
    features_drift = drift_report.get("features", {})
    severe_features = drift_report.get("severe_drift_features", [])
    moderate_features = drift_report.get("moderate_drift_features", [])
    recommendation = drift_report.get("recommendation", "UNKNOWN")

    print_header("Drift Evaluation Summary")
    print(f"[*] Max Feature PSI:             {drift_report.get('max_psi', 0.0):.4f}")
    print(
        f"[*] Severe Drift Features:       {len(severe_features)} ({', '.join(severe_features) if severe_features else 'None'})"
    )
    print(
        f"[*] Moderate Drift Features:     {len(moderate_features)} ({', '.join(moderate_features) if moderate_features else 'None'})"
    )
    print(f"[*] Overall Recommendation:      {recommendation}")

    concept_drift = result.get("concept_drift")
    if concept_drift:
        print(
            f"[*] Concept Drift Detected:      {concept_drift.get('concept_drift_detected', False)}"
        )
        print(
            f"    - Baseline Alert Rate:       {concept_drift.get('baseline_alert_rate', 0.0):.2%}"
        )
        print(
            f"    - Current Alert Rate:        {concept_drift.get('current_alert_rate', 0.0):.2%}"
        )
        print(
            f"    - Percentage Shift:          {concept_drift.get('relative_percentage_shift', 0.0):.2f}%"
        )

    if features_drift:
        print("\n  Top Feature PSI Metrics:")
        print(f"  {'Feature Name':<28} | {'PSI':<8} | {'KS p-value':<12} | {'Drift Status'}")
        print("  " + "-" * 66)
        sorted_feats = sorted(
            features_drift.items(),
            key=lambda x: x[1].get("psi_score", 0.0),
            reverse=True,
        )
        for fname, fmeta in sorted_feats[:5]:
            status_flag = "[!] DRIFT" if fmeta.get("drift_detected") else "[+] STABLE"
            print(
                f"  {fname:<28} | {fmeta.get('psi_score', 0.0):<8.4f} | {fmeta.get('ks_p_value', 1.0):<12.6f} | {status_flag}"
            )

    if not result.get("retrained"):
        print_header("Workflow Result: NO RETRAINING NEEDED")
        print("[+] Current models remain within healthy statistical distribution parameters.")
        print(f"[+] Total execution time: {time.perf_counter() - start_time:.2f} seconds.")
        print("=" * 70)
        sys.exit(0)

    # Retraining occurred
    print_header("Retraining & Model Governance Summary")
    metrics = result.get("metrics", {})
    gate_details = result.get("gate_details", {})

    print(f"[*] Candidate Version:           v{result.get('candidate_version')}")
    print(f"[*] Candidate Model Stage:       {result.get('candidate_stage')}")
    print("[*] Evaluation Metrics:")
    print(f"    - PR-AUC:                    {metrics.get('pr_auc', 0.0):.4f} (Gate: >= 0.850)")
    print(f"    - F1-Score:                  {metrics.get('f1_score', 0.0):.4f} (Gate: >= 0.800)")
    print(
        f"    - P95 Inference Latency:     {metrics.get('inference_latency_p95_ms', 0.0):.3f} ms (Gate: < 3.0 ms)"
    )
    print(
        f"    - Mean Inference Latency:    {metrics.get('inference_latency_mean_ms', 0.0):.3f} ms"
    )

    print("\n[*] Automated Promotion Gate Results:")
    evaluations = gate_details.get("evaluations", {})
    for metric_name, eval_info in evaluations.items():
        icon = "[PASS]" if eval_info.get("passed") else "[FAIL]"
        actual_val = eval_info.get("actual")
        crit_val = eval_info.get("criterion")
        print(f"    {icon} {metric_name}: actual={actual_val} (criteria: {crit_val})")

    failure_reasons = gate_details.get("failure_reasons", [])
    if failure_reasons:
        for reason in failure_reasons:
            print(f"    [!] Reason: {reason}")

    print("\n[*] Deployment Status:")
    if result.get("deployed"):
        print("[+] SUCCESS: Candidate model promoted to Production and hot-swapped at:")
        print(f"    {result.get('model_path')}")
    elif args.dry_run:
        print("[!] DRY-RUN: Model passed gates but deployment was skipped as requested.")
    else:
        print("[X] REJECTED: Candidate failed promotion gates; production model untouched.")

    print(f"\n[+] Total workflow execution time: {time.perf_counter() - start_time:.2f} seconds.")
    print("=" * 70)


if __name__ == "__main__":
    main()
