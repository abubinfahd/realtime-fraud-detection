"""Unit tests for the real-time in-process CPU inference engine."""

from pathlib import Path

import numpy as np
import pytest

from fraud_detection.core.config import settings
from fraud_detection.ml.inference import InferenceEngine, run_demo_inference


class TestInferenceEngine:
    """Test suite for InferenceEngine."""

    def test_missing_model_raises_file_not_found(self, tmp_path: Path) -> None:
        """Verify that initializing with non-existent model path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            InferenceEngine(model_path=tmp_path / "non_existent_model.joblib")

    @pytest.mark.skipif(
        not settings.MODEL_PATH.exists(),
        reason="Model artifact must be trained first (execute 'uv run fraud-train')",
    )
    def test_predict_schema_and_boundaries(self, sample_feature_vector: np.ndarray) -> None:
        """Verify that predict() outputs all expected keys and valid ranges."""
        engine = InferenceEngine()
        res = engine.predict(sample_feature_vector)

        assert "fraud_probability" in res
        assert "anomaly_score" in res
        assert "risk_score" in res
        assert "status" in res
        assert "latency_ms" in res

        assert 0.0 <= res["fraud_probability"] <= 1.0
        assert 0.0 <= res["anomaly_score"] <= 1.0
        assert 0.0 <= res["risk_score"] <= 1.0
        assert res["status"] in {"APPROVED", "FLAGGED", "REJECTED"}
        assert res["latency_ms"] > 0.0

    @pytest.mark.skipif(
        not settings.MODEL_PATH.exists(),
        reason="Model artifact must be trained first",
    )
    def test_predict_accepts_1d_and_2d_arrays(self) -> None:
        """Verify engine accepts both shape (10,) and shape (1, 10)."""
        engine = InferenceEngine()
        v_1d = np.zeros(10, dtype=np.float64)
        v_2d = np.zeros((1, 10), dtype=np.float64)

        res_1 = engine.predict(v_1d)
        res_2 = engine.predict(v_2d)

        assert res_1["status"] == res_2["status"]
        assert res_1["risk_score"] == res_2["risk_score"]

    @pytest.mark.skipif(
        not settings.MODEL_PATH.exists(),
        reason="Model artifact must be trained first",
    )
    def test_run_demo_inference_10_samples(self) -> None:
        """Verify batch inference execution across the demo 10-transaction dataset."""
        if not settings.DEMO_INFERENCE_DATA_PATH.exists():
            pytest.skip("Demo inference CSV not found")

        results = run_demo_inference(settings.DEMO_INFERENCE_DATA_PATH)
        assert len(results) == 10

        statuses = [r["status"] for r in results]
        assert "APPROVED" in statuses
        assert "REJECTED" in statuses
