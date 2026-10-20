"""Unit tests for feature engineering and real-time feature vector assembly."""

import numpy as np

from fraud_detection.ml.features import FEATURE_NAMES, extract_features


class TestFeatures:
    """Test suite for feature extraction and canonical vector schema."""

    def test_canonical_feature_names_order(self) -> None:
        """Verify the exact 10 feature names in their strictly required order."""
        expected = [
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
        assert FEATURE_NAMES == expected
        assert len(FEATURE_NAMES) == 10

    def test_extract_features_shape_and_dtype(
        self, sample_transaction_dict: dict, sample_velocity_dict: dict
    ) -> None:
        """Verify output shape and float64 type for inference."""
        vec = extract_features(sample_transaction_dict, sample_velocity_dict)
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (10,)
        assert vec.dtype == np.float64
        assert np.all(np.isfinite(vec))

    def test_extract_features_feature_values(
        self, sample_transaction_dict: dict, sample_velocity_dict: dict
    ) -> None:
        """Verify that individual feature components match input dictionary fields."""
        sample_transaction_dict["amount"] = 100.0
        sample_transaction_dict["merchant_category"] = "crypto"
        sample_transaction_dict["timestamp"] = "2026-10-20T03:00:00+00:00"  # Tuesday (weekday=1)
        sample_velocity_dict["tx_count_1m"] = 5.0
        sample_velocity_dict["tx_count_10m"] = 10.0
        sample_velocity_dict["tx_sum_10m"] = 500.0  # avg = 50.0 -> ratio = 100.0 / 50.0 = 2.0
        sample_transaction_dict["is_foreign_transaction"] = True
        sample_transaction_dict["is_new_device"] = True

        vec = extract_features(sample_transaction_dict, sample_velocity_dict)

        assert vec[0] == 100.0  # amount
        assert vec[1] == 3.0  # hour_of_day
        assert vec[2] == 1.0  # day_of_week (Tuesday = 1)
        assert vec[3] == 0.85  # merchant_category_risk (crypto)
        assert vec[4] == 5.0  # tx_count_1m
        assert vec[5] == 10.0  # tx_count_10m
        assert vec[6] == 500.0  # tx_sum_10m
        assert vec[7] == 2.0  # amount_to_avg_ratio (100 / (500/10))
        assert vec[8] == 1.0  # is_foreign_transaction
        assert vec[9] == 1.0  # is_new_device

    def test_extract_features_without_velocity_defaults(
        self, sample_transaction_dict: dict
    ) -> None:
        """Verify default fallback behavior when Redis returns no velocity data."""
        vec = extract_features(sample_transaction_dict, velocity=None)
        assert vec.shape == (10,)
        assert vec[4] == 1.0  # default tx_count_1m
        assert vec[5] == 1.0  # default tx_count_10m
        assert vec[7] == 1.0  # default amount_to_avg_ratio

    def test_extract_features_zero_division_guard(self, sample_transaction_dict: dict) -> None:
        """Verify that zero transaction counts/sums do not trigger ZeroDivisionError."""
        zero_velocity = {"tx_count_10m": 0, "tx_sum_10m": 0.0}
        vec = extract_features(sample_transaction_dict, zero_velocity)
        assert np.isfinite(vec[7])
        assert vec[7] == 1.0
