"""Unit tests for feature preprocessing and transformation utilities."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from fraud_detection.ml.features import FEATURE_NAMES
from fraud_detection.ml.preprocessing import (
    DEFAULT_CATEGORY_RISK,
    get_merchant_risk,
    parse_timestamp,
    preprocess_dataframe,
    sanitize_feature_vector,
)


class TestPreprocessing:
    """Test suite for preprocessing logic."""

    def test_get_merchant_risk_known_categories(self) -> None:
        """Verify calibrated domain risk scores for known categories."""
        assert get_merchant_risk("crypto") == 0.85
        assert get_merchant_risk("gambling") == 0.80
        assert get_merchant_risk("jewelry") == 0.70
        assert get_merchant_risk("grocery") == 0.05
        assert get_merchant_risk("utilities") == 0.02

    def test_get_merchant_risk_case_and_whitespace_insensitivity(self) -> None:
        """Verify normalization for uppercase or spaced strings."""
        assert get_merchant_risk("  CRYPTO ") == 0.85
        assert get_merchant_risk("Retail") == 0.10

    def test_get_merchant_risk_unknown_category_fallback(self) -> None:
        """Verify that unfamiliar categories fallback to median default risk."""
        assert get_merchant_risk("unknown_b2b_service") == DEFAULT_CATEGORY_RISK

    def test_parse_timestamp_iso_string(self) -> None:
        """Verify parsing of standard ISO-8601 strings."""
        dt = parse_timestamp("2026-10-20T14:30:00+00:00")
        assert dt.year == 2026
        assert dt.hour == 14
        assert dt.minute == 30

    def test_parse_timestamp_datetime_passthrough(self) -> None:
        """Verify that datetime instances are returned directly."""
        now = datetime.now(UTC)
        assert parse_timestamp(now) == now

    def test_parse_timestamp_invalid_string_fallback(self) -> None:
        """Verify graceful fallback to current time when string is corrupted."""
        dt = parse_timestamp("corrupted_invalid_timestamp_value")
        assert isinstance(dt, datetime)

    def test_sanitize_feature_vector_clean(self) -> None:
        """Verify that valid finite arrays remain unchanged."""
        clean = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
        sanitized = sanitize_feature_vector(clean)
        np.testing.assert_array_equal(clean, sanitized)

    def test_sanitize_feature_vector_nan_and_inf(self) -> None:
        """Verify that NaNs and infinities are replaced with finite defaults."""
        dirty = np.array([np.nan, np.inf, -np.inf, 42.0], dtype=np.float64)
        sanitized = sanitize_feature_vector(dirty)
        assert np.all(np.isfinite(sanitized))
        assert sanitized[0] == 0.0
        assert sanitized[1] > 0
        assert sanitized[2] < 0
        assert sanitized[3] == 42.0

    def test_preprocess_dataframe(self) -> None:
        """Verify batch DataFrame transformation into X (FEATURE_NAMES) and y."""
        df = pd.DataFrame(
            {
                "transaction_id": ["tx_1", "tx_2"],
                "amount": [50.0, 1500.0],
                "timestamp": ["2026-10-20T14:00:00Z", "2026-10-20T03:00:00Z"],
                "merchant_category": ["grocery", "crypto"],
                "tx_count_1m": [1, 2],
                "tx_count_10m": [1, 4],
                "tx_sum_10m": [50.0, 1600.0],
                "amount_to_avg_ratio": [1.0, 3.75],
                "is_foreign_transaction": [0, 1],
                "is_new_device": [0, 1],
                "is_fraud": [0, 1],
            }
        )

        X, y = preprocess_dataframe(df)

        assert list(X.columns) == FEATURE_NAMES
        assert len(X) == 2
        assert len(y) == 2
        assert y[0] == 0
        assert y[1] == 1
        assert X.loc[0, "hour_of_day"] == 14.0
        assert X.loc[1, "hour_of_day"] == 3.0
        assert X.loc[0, "merchant_category_risk"] == 0.05
        assert X.loc[1, "merchant_category_risk"] == 0.85
