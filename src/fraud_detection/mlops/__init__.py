"""MLOps Subsystem for Real-Time Fraud Detection.

Pillars:
1. Experiment Tracking: MLflow integration capturing runs, parameters, metrics, and artifacts.
2. Model Registry: Automated governance, quality gates, and model promotion.
3. Drift Monitoring: Statistical data drift (PSI, KS-test) and concept drift detection.
4. Continuous Retraining: Automated pipelines triggered by drift or schedule.
"""

from fraud_detection.mlops.tracking import ExperimentTracker, RunContext

__all__ = ["ExperimentTracker", "RunContext"]
