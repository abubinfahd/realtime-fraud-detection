"""Unit tests for FastAPI endpoints (health checks and real-time inference API)."""

import pytest
from fastapi.testclient import TestClient

from fraud_detection.core.config import settings


class TestAPIEndpoints:
    """Test suite for FastAPI endpoints."""

    def test_root_endpoint(self, client: TestClient) -> None:
        """Verify root endpoint returns operational metadata and documentation paths."""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "operational"
        assert "docs" in data
        assert "version" in data

    def test_healthz_endpoint(self, client: TestClient) -> None:
        """Verify healthz endpoint probe."""
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "model_loaded" in data
        assert data["service"] == "fraud-detection-api"

    @pytest.mark.skipif(
        not settings.MODEL_PATH.exists(),
        reason="Model artifact must be trained first",
    )
    def test_predict_endpoint(self, client: TestClient, sample_transaction_dict: dict) -> None:
        """Verify POST /api/v1/predict returns fraud probability and decision status."""
        resp = client.post("/api/v1/predict", json=sample_transaction_dict)
        assert resp.status_code == 200
        data = resp.json()

        assert data["transaction_id"] == sample_transaction_dict["transaction_id"]
        assert data["status"] in {"APPROVED", "FLAGGED", "REJECTED"}
        assert 0.0 <= data["risk_score"] <= 1.0
        assert 0.0 <= data["fraud_probability"] <= 1.0
        assert 0.0 <= data["anomaly_score"] <= 1.0
        assert data["latency_ms"] > 0.0
