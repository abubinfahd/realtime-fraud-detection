"""Unit tests for model evaluation and decision threshold optimization."""

import numpy as np

from fraud_detection.ml.evaluate import evaluate_classifier, find_optimal_f1_threshold


class TestEvaluation:
    """Test suite for classification evaluation metrics."""

    def test_find_optimal_f1_threshold_range(self) -> None:
        """Verify that optimized threshold lies within the valid probability range [0, 1]."""
        np.random.seed(42)
        y_true = np.array([0] * 90 + [1] * 10)
        y_probs = np.concatenate(
            [
                np.random.beta(1, 10, size=90),  # Low probabilities for legit
                np.random.beta(8, 2, size=10),  # High probabilities for fraud
            ]
        )

        threshold = find_optimal_f1_threshold(y_true, y_probs)
        assert 0.0 <= threshold <= 1.0

    def test_evaluate_classifier_output_schema(self) -> None:
        """Verify that evaluate_classifier returns all required evaluation metrics."""
        y_true = np.array([0, 0, 0, 0, 0, 0, 1, 1, 1, 1])
        y_probs = np.array([0.05, 0.10, 0.15, 0.20, 0.35, 0.45, 0.60, 0.75, 0.85, 0.95])

        results = evaluate_classifier(y_true, y_probs, threshold=0.50)

        assert "pr_auc" in results
        assert "roc_auc" in results
        assert "f1_score" in results
        assert "precision" in results
        assert "recall" in results
        assert "confusion_matrix" in results

        cm = results["confusion_matrix"]
        assert cm["true_negatives"] == 6
        assert cm["false_positives"] == 0
        assert cm["false_negatives"] == 0
        assert cm["true_positives"] == 4

        total_cm_samples = (
            cm["true_negatives"]
            + cm["false_positives"]
            + cm["false_negatives"]
            + cm["true_positives"]
        )
        assert total_cm_samples == len(y_true)
        assert results["f1_score"] == 1.0
        assert results["precision"] == 1.0
        assert results["recall"] == 1.0

    def test_evaluate_classifier_imbalanced_minority_detection(self) -> None:
        """Verify PR-AUC and metrics on heavily imbalanced class distribution."""
        np.random.seed(42)
        y_true = np.array([0] * 990 + [1] * 10)
        y_probs = np.concatenate(
            [
                np.random.uniform(0.01, 0.20, size=990),
                np.random.uniform(0.70, 0.99, size=10),
            ]
        )

        metrics = evaluate_classifier(y_true, y_probs)
        assert metrics["pr_auc"] > 0.80
        assert metrics["roc_auc"] > 0.95
