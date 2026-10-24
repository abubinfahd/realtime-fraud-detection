"""Unit tests for FastAPI endpoints (health checks, telemetry, alerts, and inference)."""

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
        assert "dashboard" in data
        assert "docs" in data
        assert "version" in data
        assert "websocket_stream" in data
        assert "metrics" in data

    def test_healthz_endpoint(self, client: TestClient) -> None:
        """Verify comprehensive healthz probe returns component details."""
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")
        assert data["service"] == "fraud-detection-api"
        assert "components" in data
        assert "ml_inference_engine" in data["components"]
        assert "redis_pubsub" in data["components"]
        assert "postgres_database" in data["components"]

    def test_livez_and_readyz_probes(self, client: TestClient) -> None:
        """Verify Kubernetes liveness and readiness probes."""
        live_resp = client.get("/livez")
        assert live_resp.status_code == 200
        assert live_resp.json()["status"] == "alive"

        ready_resp = client.get("/readyz")
        assert ready_resp.status_code in (200, 503)

    def test_metrics_endpoints(self, client: TestClient) -> None:
        """Verify gateway telemetry and metrics endpoints."""
        resp = client.get("/api/v1/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "fraud-detection-gateway"
        assert "active_websocket_clients" in data
        assert "total_broadcasts" in data
        assert "total_frames_delivered" in data
        assert data["uptime_seconds"] >= 0.0

        stats_resp = client.get("/api/v1/stats")
        assert stats_resp.status_code == 200
        assert "active_clients" in stats_resp.json()

    def test_recent_alerts_endpoint(self, client: TestClient) -> None:
        """Verify /api/v1/alerts/recent returns threat records for hydration."""
        resp = client.get("/api/v1/alerts/recent?limit=10")
        assert resp.status_code == 200
        alerts = resp.json()
        assert isinstance(alerts, list)
        assert len(alerts) >= 1
        first = alerts[0]
        assert "transaction_ref" in first
        assert "status" in first
        assert "risk_score" in first
        assert first["status"] in ("FLAGGED", "REJECTED")

    def test_alerts_summary_endpoint(self, client: TestClient) -> None:
        """Verify /api/v1/alerts/summary returns status aggregation breakdown."""
        resp = client.get("/api/v1/alerts/summary")
        assert resp.status_code == 200
        summary = resp.json()
        assert "total" in summary
        assert "approved_count" in summary
        assert "flagged_count" in summary
        assert "rejected_count" in summary

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

    def test_dashboard_mount(self, client: TestClient) -> None:
        """Verify dashboard HTML is served at /dashboard/."""
        resp = client.get("/dashboard/")
        assert resp.status_code == 200
        assert "FraudShield AI" in resp.text
        assert "Real-Time Threat Intelligence Feed" in resp.text
        assert "app.js" in resp.text

    def test_dashboard_static_assets(self, client: TestClient) -> None:
        """Verify dashboard client JavaScript asset is served at /dashboard/app.js."""
        resp = client.get("/dashboard/app.js")
        assert resp.status_code == 200
        assert "WebSocket" in resp.text
        assert "playAlertChime" in resp.text
