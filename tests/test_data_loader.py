"""Unit tests for synthetic transaction generator and data loader."""

from pathlib import Path

import pytest

from fraud_detection.core.config import settings
from fraud_detection.ml.data_loader import (
    generate_10k_realistic_transactions,
    load_or_generate_dataset,
)


class TestDataLoader:
    """Test suite for transaction data generation and loading."""

    def test_generate_small_realistic_transactions(self, tmp_path: Path) -> None:
        """Verify generator produces valid schema and correct fraud count on small sample."""
        out_csv = tmp_path / "test_sample_100.csv"
        df = generate_10k_realistic_transactions(
            output_path=out_csv,
            n_samples=100,
            fraud_rate=0.05,
            random_seed=42,
        )

        assert len(df) == 100
        assert out_csv.exists()
        assert int(df["is_fraud"].sum()) == 5
        assert "transaction_id" in df.columns
        assert "amount" in df.columns
        assert "merchant_category" in df.columns
        assert "tx_count_1m" in df.columns
        assert "tx_sum_10m" in df.columns

    @pytest.mark.skipif(
        not settings.DEMO_DATA_PATH.exists(),
        reason="10k dataset CSV not generated",
    )
    def test_load_or_generate_dataset_loads_existing_10k(self) -> None:
        """Verify that load_or_generate_dataset loads the full 10,000 transaction CSV."""
        df = load_or_generate_dataset()
        assert len(df) == 10000
        assert int(df["is_fraud"].sum()) == 100
        assert df["amount"].min() > 0.0
