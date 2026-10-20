"""
Model evaluation and threshold optimization module.

Calculates Precision-Recall AUC (PR-AUC), ROC-AUC, optimizes decision
thresholds for F1-score maximization, and reports detailed confusion matrices.
"""

from typing import Any

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)

from fraud_detection.core.logger import get_logger

logger = get_logger(__name__)


def find_optimal_f1_threshold(y_true: np.ndarray, y_probs: np.ndarray) -> float:
    """Find the decision threshold that maximizes the F1-score."""
    precisions, recalls, thresholds = precision_recall_curve(y_true, y_probs)
    f1_scores = np.where(
        (precisions + recalls) > 0,
        2 * (precisions * recalls) / (precisions + recalls),
        0.0,
    )
    optimal_idx = int(np.argmax(f1_scores))
    optimal_threshold = float(thresholds[min(optimal_idx, len(thresholds) - 1)])
    return optimal_threshold


def evaluate_classifier(
    y_true: np.ndarray,
    y_probs: np.ndarray,
    threshold: float | None = None,
) -> dict[str, Any]:
    """
    Perform comprehensive classification evaluation on holdout predictions.

    Parameters
    ----------
    y_true : np.ndarray
        Ground truth binary labels (0 = legit, 1 = fraud).
    y_probs : np.ndarray
        Predicted fraud probabilities.
    threshold : float | None
        Classification threshold. If None, computes optimal F1 threshold.

    Returns
    -------
    dict[str, Any]
        Dictionary of metrics (PR-AUC, ROC-AUC, F1, Precision, Recall, Confusion Matrix).
    """
    pr_auc = float(average_precision_score(y_true, y_probs))
    roc_auc = float(roc_auc_score(y_true, y_probs))

    if threshold is None:
        threshold = find_optimal_f1_threshold(y_true, y_probs)

    y_pred = (y_probs >= threshold).astype(int)
    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel()

    precision = float(precision_score(y_true, y_pred, zero_division=0))
    recall = float(recall_score(y_true, y_pred, zero_division=0))
    f1 = float(f1_score(y_true, y_pred, zero_division=0))

    metrics = {
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "threshold": threshold,
        "f1_score": f1,
        "precision": precision,
        "recall": recall,
        "confusion_matrix": {
            "true_negatives": int(tn),
            "false_positives": int(fp),
            "false_negatives": int(fn),
            "true_positives": int(tp),
        },
    }

    logger.info("Evaluation completed", extra={"pr_auc": pr_auc, "f1": f1, "threshold": threshold})
    return metrics
