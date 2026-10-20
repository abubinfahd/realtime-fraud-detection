"""Pytest shared test fixtures and configuration."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fraud_detection.api.app import create_app
from fraud_detection.core.config import settings


@pytest.fixture
def sample_transaction_dict() -> dict:
    """Fixture providing a standard valid transaction attribute dictionary."""
    return {
        "transaction_id": f"tx_test_{uuid4().hex[:8]}",
        "user_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
        "account_id": "a1eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
        "amount": 75.50,
        "currency": "USD",
        "merchant_category": "retail",
        "merchant_name": "Target",
        "location_country": "US",
        "location_city": "New York",
        "location_lat": 40.7128,
        "location_lon": -74.0060,
        "device_id": "dev_test_fixture_1",
        "ip_address": "192.168.1.50",
        "timestamp": datetime.now(UTC).isoformat(),
        "is_foreign_transaction": False,
        "is_new_device": False,
    }


@pytest.fixture
def sample_velocity_dict() -> dict:
    """Fixture providing simulated Redis sliding-window metrics."""
    return {
        "tx_count_1m": 1.0,
        "tx_count_10m": 2.0,
        "tx_sum_10m": 120.00,
    }


@pytest.fixture
def sample_feature_vector() -> np.ndarray:
    """Fixture providing a 10-dimensional feature array conforming to FEATURE_NAMES."""
    # ['amount', 'hour_of_day', 'day_of_week', 'merchant_category_risk',
    #  'tx_count_1m', 'tx_count_10m', 'tx_sum_10m', 'amount_to_avg_ratio',
    #  'is_foreign_transaction', 'is_new_device']
    return np.array(
        [75.50, 14.0, 1.0, 0.10, 1.0, 2.0, 120.00, 1.25, 0.0, 0.0],
        dtype=np.float64,
    )


@pytest.fixture
def model_artifact_path() -> Path:
    """Fixture returning the expected model artifact path."""
    return settings.MODEL_PATH


@pytest.fixture
def client():
    """Fixture providing an active FastAPI TestClient."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
