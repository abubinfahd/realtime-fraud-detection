"""Statistical Data Drift & Concept Drift Detection Engine.

Pillars:
1. Population Stability Index (PSI):
   Measures distributional divergence between training baseline and streaming production data.
   - PSI < 0.10: No significant drift (Stable).
   - 0.10 <= PSI < 0.25: Moderate drift (Warning / Log).
   - PSI >= 0.25: Severe drift (Action required / Retraining trigger).

2. Kolmogorov-Smirnov (KS-Test):
   Two-sample non-parametric test evaluating if current sample originates from the baseline distribution.
   - p-value < 0.05 indicates statistically significant distribution divergence.

3. Concept Drift (Target Drift):
   Tracks shifts in positive fraud prediction rates and anomaly distributions over time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from fraud_detection.core.logger import get_logger

logger = get_logger("fraud_detection.mlops.drift_detector")

PSI_STABLE_THRESHOLD = 0.10
PSI_SEVERE_THRESHOLD = 0.25
DEFAULT_ALPHA = 0.05


@dataclass
class FeatureDriftResult:
    """Statistical drift evaluation metrics for a single numerical feature."""

    feature_name: str
    psi_score: float
    drift_severity: str  # "NO_DRIFT" | "MODERATE_DRIFT" | "SEVERE_DRIFT"
    drift_detected: bool
    ks_statistic: float
    ks_p_value: float
    mean_baseline: float
    mean_current: float
    std_baseline: float
    std_current: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to dictionary."""
        return asdict(self)


@dataclass
class DriftReport:
    """Comprehensive multi-feature drift assessment report across pipeline inputs."""

    timestamp: str
    sample_size_baseline: int
    sample_size_current: int
    features: dict[str, FeatureDriftResult]
    overall_drift_detected: bool
    severe_drift_features: list[str]
    moderate_drift_features: list[str]
    max_psi: float
    recommendation: str  # "STABLE" | "WARNING_MONITOR" | "RETRAINING_RECOMMENDED"

    def to_dict(self) -> dict[str, Any]:
        """Serialize drift report to dictionary."""
        data = asdict(self)
        data["features"] = {k: v.to_dict() for k, v in self.features.items()}
        return data


class DriftDetector:
    """Calculates distribution divergence statistics and generates drift reports."""

    def __init__(
        self,
        baseline_df: pd.DataFrame | None = None,
        psi_threshold: float = PSI_SEVERE_THRESHOLD,
        alpha: float = DEFAULT_ALPHA,
        num_bins: int = 10,
    ) -> None:
        self.baseline_df = baseline_df
        self.psi_threshold = psi_threshold
        self.alpha = alpha
        self.num_bins = num_bins

    @staticmethod
    def calculate_psi(
        baseline: np.ndarray | pd.Series,
        current: np.ndarray | pd.Series,
        num_bins: int = 10,
        epsilon: float = 1e-4,
    ) -> float:
        """
        Calculate Population Stability Index (PSI) between two continuous distributions.

        PSI = sum((Actual_% - Expected_%) * ln(Actual_% / Expected_%))
        """
        b_clean = np.asarray(baseline, dtype=np.float64)
        c_clean = np.asarray(current, dtype=np.float64)

        # Filter NaNs and Infs
        b_clean = b_clean[np.isfinite(b_clean)]
        c_clean = c_clean[np.isfinite(c_clean)]

        if len(b_clean) == 0 or len(c_clean) == 0:
            return 0.0

        # Identical distribution short-circuit
        if np.array_equal(b_clean, c_clean):
            return 0.0

        # Establish bin edges from baseline quantiles to ensure balanced expected bins
        percentiles = np.linspace(0, 100, num_bins + 1)
        bin_edges = np.percentile(b_clean, percentiles)
        bin_edges = np.unique(bin_edges)

        # Fallback to uniform binning if quantiles are degenerate (e.g. constant values)
        if len(bin_edges) <= 2:
            min_val = min(float(np.min(b_clean)), float(np.min(c_clean)))
            max_val = max(float(np.max(b_clean)), float(np.max(c_clean)))
            if min_val == max_val:
                return 0.0
            bin_edges = np.linspace(min_val, max_val, num_bins + 1)

        # Ensure infinite boundary coverage
        bin_edges[0] = -np.inf
        bin_edges[-1] = np.inf

        # Calculate frequency counts in each bin
        b_counts, _ = np.histogram(b_clean, bins=bin_edges)
        c_counts, _ = np.histogram(c_clean, bins=bin_edges)

        # Convert to fractional probabilities with smoothing epsilon
        b_pct = (b_counts / len(b_clean)) + epsilon
        c_pct = (c_counts / len(c_clean)) + epsilon

        # Re-normalize probabilities
        b_pct = b_pct / np.sum(b_pct)
        c_pct = c_pct / np.sum(c_pct)

        # PSI computation
        psi_val = np.sum((c_pct - b_pct) * np.log(c_pct / b_pct))
        return float(round(max(0.0, float(psi_val)), 4))

    @staticmethod
    def calculate_ks_test(
        baseline: np.ndarray | pd.Series,
        current: np.ndarray | pd.Series,
    ) -> tuple[float, float]:
        """Calculate two-sample Kolmogorov-Smirnov test statistic and asymptotic p-value."""
        b_clean = np.asarray(baseline, dtype=np.float64)
        c_clean = np.asarray(current, dtype=np.float64)
        b_clean = b_clean[np.isfinite(b_clean)]
        c_clean = c_clean[np.isfinite(c_clean)]

        if len(b_clean) == 0 or len(c_clean) == 0:
            return 0.0, 1.0

        res = ks_2samp(b_clean, c_clean)
        return float(round(res.statistic, 4)), float(round(res.pvalue, 6))

    def evaluate_feature(
        self,
        feature_name: str,
        baseline: np.ndarray | pd.Series,
        current: np.ndarray | pd.Series,
    ) -> FeatureDriftResult:
        """Evaluate drift metrics for a single numerical feature."""
        b_arr = np.asarray(baseline, dtype=np.float64)
        c_arr = np.asarray(current, dtype=np.float64)

        psi = self.calculate_psi(b_arr, c_arr, num_bins=self.num_bins)
        ks_stat, ks_pval = self.calculate_ks_test(b_arr, c_arr)

        if psi >= self.psi_threshold:
            severity = "SEVERE_DRIFT"
            drift_detected = True
        elif psi >= PSI_STABLE_THRESHOLD:
            severity = "MODERATE_DRIFT"
            drift_detected = ks_pval < self.alpha
        else:
            severity = "NO_DRIFT"
            drift_detected = False

        return FeatureDriftResult(
            feature_name=feature_name,
            psi_score=psi,
            drift_severity=severity,
            drift_detected=drift_detected,
            ks_statistic=ks_stat,
            ks_p_value=ks_pval,
            mean_baseline=float(round(np.mean(b_arr), 4)) if len(b_arr) else 0.0,
            mean_current=float(round(np.mean(c_arr), 4)) if len(c_arr) else 0.0,
            std_baseline=float(round(np.std(b_arr), 4)) if len(b_arr) else 0.0,
            std_current=float(round(np.std(c_arr), 4)) if len(c_arr) else 0.0,
        )

    def evaluate_drift(
        self,
        current_df: pd.DataFrame,
        baseline_df: pd.DataFrame | None = None,
        feature_columns: list[str] | None = None,
    ) -> DriftReport:
        """
        Evaluate multi-feature dataset drift against training baseline.

        Parameters
        ----------
        current_df : pd.DataFrame
            Recent production/streaming transactions to evaluate.
        baseline_df : pd.DataFrame | None
            Training reference baseline (falls back to self.baseline_df).
        feature_columns : list[str] | None
            Subset of numerical features to evaluate.
        """
        base = baseline_df if baseline_df is not None else self.baseline_df
        if base is None:
            raise ValueError(
                "Baseline DataFrame must be provided either in __init__ or evaluate_drift."
            )

        # Determine shared numeric columns
        cols = feature_columns
        if cols is None:
            shared = [c for c in base.columns if c in current_df.columns]
            cols = [
                c
                for c in shared
                if pd.api.types.is_numeric_dtype(base[c])
                and pd.api.types.is_numeric_dtype(current_df[c])
            ]

        results: dict[str, FeatureDriftResult] = {}
        severe_features: list[str] = []
        moderate_features: list[str] = []

        for col in cols:
            res = self.evaluate_feature(
                feature_name=col,
                baseline=base[col].values,
                current=current_df[col].values,
            )
            results[col] = res
            if res.drift_severity == "SEVERE_DRIFT":
                severe_features.append(col)
            elif res.drift_severity == "MODERATE_DRIFT":
                moderate_features.append(col)

        max_psi = max([r.psi_score for r in results.values()]) if results else 0.0
        overall_detected = len(severe_features) > 0 or len(moderate_features) >= 2

        if len(severe_features) > 0:
            recommendation = "RETRAINING_RECOMMENDED"
        elif len(moderate_features) > 0:
            recommendation = "WARNING_MONITOR"
        else:
            recommendation = "STABLE"

        report = DriftReport(
            timestamp=datetime.now(UTC).isoformat(),
            sample_size_baseline=len(base),
            sample_size_current=len(current_df),
            features=results,
            overall_drift_detected=overall_detected,
            severe_drift_features=severe_features,
            moderate_drift_features=moderate_features,
            max_psi=max_psi,
            recommendation=recommendation,
        )

        return report

    @staticmethod
    def evaluate_concept_drift(
        baseline_predictions: np.ndarray,
        current_predictions: np.ndarray,
        alert_threshold: float = 0.50,
    ) -> dict[str, Any]:
        """
        Detect Target/Concept Drift by analyzing shifts in fraud probability distributions.

        Parameters
        ----------
        baseline_predictions : np.ndarray
            Fraud probabilities emitted on test/validation baseline.
        current_predictions : np.ndarray
            Fraud probabilities emitted on recent production traffic.
        """
        b_clean = np.asarray(baseline_predictions, dtype=np.float64)
        c_clean = np.asarray(current_predictions, dtype=np.float64)

        b_alert_rate = float(np.mean(b_clean >= alert_threshold))
        c_alert_rate = float(np.mean(c_clean >= alert_threshold))

        rate_diff = c_alert_rate - b_alert_rate
        relative_jump = (rate_diff / max(b_alert_rate, 1e-4)) * 100.0

        concept_drift = abs(rate_diff) >= 0.05 or abs(relative_jump) >= 50.0

        return {
            "baseline_alert_rate": round(b_alert_rate, 4),
            "current_alert_rate": round(c_alert_rate, 4),
            "absolute_difference": round(rate_diff, 4),
            "relative_percentage_shift": round(relative_jump, 2),
            "concept_drift_detected": concept_drift,
            "status": "CONCEPT_DRIFT_ALERT" if concept_drift else "STABLE",
        }
