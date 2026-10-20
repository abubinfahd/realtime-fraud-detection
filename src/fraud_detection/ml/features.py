"""
Canonical feature schema and real-time vector assembly.

Defines the single source of truth for all feature names, column order,
and extraction logic across offline training and real-time inference.
"""

from collections.abc import Mapping
from typing import Any

import numpy as np

from fraud_detection.ml.preprocessing import (
    get_merchant_risk,
    parse_timestamp,
    sanitize_feature_vector,
)

# Canonical feature list with strictly enforced order
FEATURE_NAMES: list[str] = [
    "amount",
    "hour_of_day",
    "day_of_week",
    "merchant_category_risk",
    "tx_count_1m",
    "tx_count_10m",
    "tx_sum_10m",
    "amount_to_avg_ratio",
    "is_foreign_transaction",
    "is_new_device",
]


def extract_features(
    transaction: Mapping[str, Any],
    velocity: Mapping[str, Any] | None = None,
) -> np.ndarray:
    """
    Extract and assemble a 1D feature vector conforming to FEATURE_NAMES.

    Parameters
    ----------
    transaction : Mapping[str, Any]
        Raw transaction attributes (amount, merchant_category, timestamp, etc.).
    velocity : Mapping[str, Any] | None
        Sliding-window velocity features retrieved from Redis (tx_count_1m, tx_sum_10m, etc.).

    Returns
    -------
    np.ndarray
        Shape (10,), dtype float64 vector ready for model evaluation.
    """
    if velocity is None:
        velocity = {}

    amount = float(transaction.get("amount", 0.0))

    dt = parse_timestamp(transaction.get("timestamp"))
    hour_of_day = float(dt.hour)
    day_of_week = float(dt.weekday())

    category = str(transaction.get("merchant_category", "retail"))
    merchant_risk = get_merchant_risk(category)

    # Dynamic Redis velocity signals
    tx_count_1m = float(velocity.get("tx_count_1m", 1.0))
    tx_count_10m = float(velocity.get("tx_count_10m", 1.0))
    tx_sum_10m = float(velocity.get("tx_sum_10m", amount))

    # Ratio of current amount to 10-minute average spend
    if tx_count_10m > 0 and tx_sum_10m > 0:
        avg_spend_10m = tx_sum_10m / tx_count_10m
        amount_to_avg_ratio = amount / max(avg_spend_10m, 1.0)
    else:
        amount_to_avg_ratio = 1.0

    # Binary flags
    is_foreign = float(bool(transaction.get("is_foreign_transaction", False)))
    is_new_device = float(bool(transaction.get("is_new_device", False)))

    # Assemble vector in exact FEATURE_NAMES order
    vector = np.array(
        [
            amount,
            hour_of_day,
            day_of_week,
            merchant_risk,
            tx_count_1m,
            tx_count_10m,
            tx_sum_10m,
            amount_to_avg_ratio,
            is_foreign,
            is_new_device,
        ],
        dtype=np.float64,
    )

    return sanitize_feature_vector(vector)
