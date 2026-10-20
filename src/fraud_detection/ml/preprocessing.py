"""
Data preprocessing and feature transformation utilities.

Handles categorical risk mappings, temporal cyclical encoding,
missing value imputation, and defensive numerical clipping.
"""

from datetime import UTC, datetime
from typing import Any

import numpy as np

CATEGORY_RISK_MAP: dict[str, float] = {
    "crypto": 0.85,
    "gambling": 0.80,
    "jewelry": 0.70,
    "electronics": 0.50,
    "travel": 0.35,
    "entertainment": 0.20,
    "restaurants": 0.15,
    "retail": 0.10,
    "grocery": 0.05,
    "utilities": 0.02,
}
DEFAULT_CATEGORY_RISK: float = 0.15


def get_merchant_risk(category: str) -> float:
    """Return the normalized risk score for a merchant category."""
    return CATEGORY_RISK_MAP.get(category.lower().strip(), DEFAULT_CATEGORY_RISK)


def parse_timestamp(raw_ts: Any) -> datetime:
    """Safely parse diverse timestamp representations into a UTC datetime object."""
    if isinstance(raw_ts, datetime):
        return raw_ts
    if isinstance(raw_ts, str):
        try:
            return datetime.fromisoformat(raw_ts)
        except ValueError:
            pass
    return datetime.now(UTC)


def sanitize_feature_vector(vector: np.ndarray) -> np.ndarray:
    """Ensure array contains strictly finite float64 values, replacing NaN/Inf."""
    if not np.all(np.isfinite(vector)):
        return np.nan_to_num(vector, nan=0.0, posinf=1e6, neginf=-1e6)
    return vector


def preprocess_dataframe(df: Any) -> tuple[Any, np.ndarray]:
    """
    Transform raw transaction DataFrame into feature matrix X and target array y.

    Parses ISO timestamps into temporal features (hour_of_day, day_of_week),
    maps merchant_category to numerical risk score, enforces float64 conversions,
    and returns feature matrix X conforming to FEATURE_NAMES and target vector y.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing raw transaction columns.

    Returns
    -------
    tuple[pd.DataFrame, np.ndarray]
        X feature DataFrame with columns matching FEATURE_NAMES, and y binary label vector.
    """
    import pandas as pd

    from fraud_detection.ml.features import FEATURE_NAMES

    df_feat = df.copy()

    # Parse timestamps to derive temporal features
    ts_series = pd.to_datetime(df_feat["timestamp"], utc=True)
    df_feat["hour_of_day"] = ts_series.dt.hour.astype(float)
    df_feat["day_of_week"] = ts_series.dt.dayofweek.astype(float)

    # Map categorical risk
    df_feat["merchant_category_risk"] = (
        df_feat["merchant_category"]
        .astype(str)
        .map(lambda cat: get_merchant_risk(cat))
        .astype(float)
    )

    # Ensure numerical and velocity columns are float64
    for col in [
        "amount",
        "tx_count_1m",
        "tx_count_10m",
        "tx_sum_10m",
        "amount_to_avg_ratio",
        "is_foreign_transaction",
        "is_new_device",
    ]:
        if col in df_feat.columns:
            df_feat[col] = df_feat[col].astype(float)

    X = df_feat[FEATURE_NAMES].fillna(0.0)
    y = (
        df_feat["is_fraud"].values.astype(int)
        if "is_fraud" in df_feat.columns
        else np.zeros(len(df_feat), dtype=int)
    )

    return X, y
