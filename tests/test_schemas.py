"""Unit tests for Pydantic transaction and alert event schemas."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from fraud_detection.schemas.alert import FraudAlertEvent
from fraud_detection.schemas.transaction import TransactionEvent


class TestTransactionEventSchema:
    """Test suite for TransactionEvent validation."""

    def test_valid_transaction_event(self, sample_transaction_dict: dict) -> None:
        """Verify that a well-formed transaction event parses cleanly."""
        event = TransactionEvent(**sample_transaction_dict)
        assert event.transaction_id == sample_transaction_dict["transaction_id"]
        assert isinstance(event.user_id, UUID)
        assert isinstance(event.account_id, UUID)
        assert event.amount == 75.50
        assert event.currency == "USD"
        assert event.merchant_category == "retail"
        assert event.is_foreign_transaction is False

    def test_merchant_category_normalization(self, sample_transaction_dict: dict) -> None:
        """Verify that merchant_category is automatically trimmed and lowercased."""
        sample_transaction_dict["merchant_category"] = "  CRYPTO  "
        event = TransactionEvent(**sample_transaction_dict)
        assert event.merchant_category == "crypto"

    def test_invalid_zero_amount_raises_error(self, sample_transaction_dict: dict) -> None:
        """Verify that non-positive amount raises Pydantic ValidationError."""
        sample_transaction_dict["amount"] = 0.0
        with pytest.raises(ValidationError) as exc:
            TransactionEvent(**sample_transaction_dict)
        assert "greater than 0" in str(exc.value)

    def test_invalid_negative_amount_raises_error(self, sample_transaction_dict: dict) -> None:
        """Verify that negative amounts are rejected."""
        sample_transaction_dict["amount"] = -10.50
        with pytest.raises(ValidationError):
            TransactionEvent(**sample_transaction_dict)

    def test_invalid_latitude_raises_error(self, sample_transaction_dict: dict) -> None:
        """Verify latitude constraints (-90 <= lat <= 90)."""
        sample_transaction_dict["location_lat"] = 95.0
        with pytest.raises(ValidationError):
            TransactionEvent(**sample_transaction_dict)

    def test_invalid_longitude_raises_error(self, sample_transaction_dict: dict) -> None:
        """Verify longitude constraints (-180 <= lon <= 180)."""
        sample_transaction_dict["location_lon"] = -185.0
        with pytest.raises(ValidationError):
            TransactionEvent(**sample_transaction_dict)


class TestFraudAlertEventSchema:
    """Test suite for FraudAlertEvent validation."""

    def test_valid_fraud_alert_creation(self) -> None:
        """Verify proper alert structure and serializability."""
        alert = FraudAlertEvent(
            alert_id=f"alt_{uuid4()}",
            transaction_id="tx_12345",
            user_id=uuid4(),
            account_id=uuid4(),
            amount=3500.0,
            currency="USD",
            merchant_name="Binance Global",
            merchant_category="crypto",
            fraud_probability=0.9850,
            anomaly_score=0.8200,
            risk_score=0.9272,
            decision="REJECTED",
            reasons=["Velocity burst", "Foreign high-risk merchant"],
            timestamp=datetime.now(UTC),
        )

        assert alert.decision == "REJECTED"
        assert alert.risk_score > 0.90
        assert len(alert.reasons) == 2

        # Verify JSON dump
        json_payload = alert.model_dump_json()
        assert "tx_12345" in json_payload
        assert "Binance Global" in json_payload
