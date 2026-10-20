"""Machine learning pipeline package."""

from fraud_detection.ml.data_loader import (
    generate_10k_realistic_transactions,
    load_or_generate_dataset,
)
from fraud_detection.ml.evaluate import evaluate_classifier, find_optimal_f1_threshold
from fraud_detection.ml.features import FEATURE_NAMES, extract_features
from fraud_detection.ml.inference import InferenceEngine, run_demo_inference
from fraud_detection.ml.preprocessing import preprocess_dataframe
from fraud_detection.ml.train import train_and_evaluate

__all__ = [
    "FEATURE_NAMES",
    "InferenceEngine",
    "evaluate_classifier",
    "extract_features",
    "find_optimal_f1_threshold",
    "generate_10k_realistic_transactions",
    "load_or_generate_dataset",
    "preprocess_dataframe",
    "run_demo_inference",
    "train_and_evaluate",
]
