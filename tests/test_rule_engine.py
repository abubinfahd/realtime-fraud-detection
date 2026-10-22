"""Unit tests for the Deterministic Rule Engine."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from fraud_detection.ml.inference import InferenceEngine
from fraud_detection.rules.rule_engine import (
    HighValueThresholdRule,
    ImpossibleTravelRule,
    NocturnalDeviceRule,
    RuleEngine,
    SanctionedCountryRule,
    VelocityBurstRule,
    calculate_haversine_distance_km,
)


class TestHaversineDistance:
    """Verify great-circle distance accuracy."""

    def test_same_point_is_zero(self) -> None:
        dist = calculate_haversine_distance_km(40.7128, -74.0060, 40.7128, -74.0060)
        assert pytest.approx(dist, abs=1e-4) == 0.0

    def test_tokyo_to_london(self) -> None:
        # Tokyo (35.6762, 139.6503) to London (51.5074, -0.1278) ~9,560 km
        dist = calculate_haversine_distance_km(35.6762, 139.6503, 51.5074, -0.1278)
        assert 9500.0 < dist < 9700.0


class TestIndividualRules:
    """Verify individual deterministic rule logic."""

    def test_velocity_burst_rule(self) -> None:
        rule = VelocityBurstRule(threshold_count=8)

        # Under threshold
        res = rule.evaluate({}, velocity={"tx_count_1m": 7})
        assert res is None

        # At or above threshold
        res = rule.evaluate({}, velocity={"tx_count_1m": 8})
        assert res is not None
        assert res.rule_code == "RULE_01"
        assert res.override_verdict == "REJECTED"
        assert res.penalty_score == 1.0

    def test_high_value_rule(self) -> None:
        rule = HighValueThresholdRule(threshold_amount=25000.0)

        # Under threshold
        res = rule.evaluate({"amount": 24999.99})
        assert res is None

        # At threshold
        res = rule.evaluate({"amount": 25000.00})
        assert res is not None
        assert res.rule_code == "RULE_02"
        assert res.override_verdict == "FLAGGED"
        assert res.penalty_score == 0.35

    def test_impossible_travel_rule(self) -> None:
        rule = ImpossibleTravelRule(max_speed_kmh=900.0, min_distance_km=50.0)

        # Tokyo to London in 3 minutes (180s) -> Speed > 100,000 km/h -> REJECTED
        t0 = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
        t1 = datetime(2026, 10, 22, 12, 3, 0, tzinfo=UTC)

        last_loc = {
            "lat": 35.6762,
            "lon": 139.6503,
            "timestamp_ms": int(t0.timestamp() * 1000),
        }
        curr_tx = {
            "location_lat": 51.5074,
            "location_lon": -0.1278,
            "timestamp": t1.isoformat(),
        }

        res = rule.evaluate(curr_tx, last_location=last_loc)
        assert res is not None
        assert res.rule_code == "RULE_03"
        assert res.override_verdict == "REJECTED"
        assert "Geographic impossibility" in res.description

        # Same trip over 16 hours (57600s) -> speed ~597 km/h < 900 km/h -> None
        t2 = datetime(2026, 10, 23, 4, 0, 0, tzinfo=UTC)
        curr_tx_slow = {
            "location_lat": 51.5074,
            "location_lon": -0.1278,
            "timestamp": t2.isoformat(),
        }
        assert rule.evaluate(curr_tx_slow, last_location=last_loc) is None

        # Short local distance (< 50 km)
        near_loc = {"lat": 40.7128, "lon": -74.0060, "timestamp_ms": int(t0.timestamp() * 1000)}
        near_tx = {
            "location_lat": 40.7300,
            "location_lon": -74.0100,
            "timestamp": t1.isoformat(),
        }
        assert rule.evaluate(near_tx, last_location=near_loc) is None

    def test_sanctioned_country_rule(self) -> None:
        rule = SanctionedCountryRule()

        for code in ["IR", "KP", "SY", "CU", "ir", "kp"]:
            res = rule.evaluate({"location_country": code})
            assert res is not None
            assert res.rule_code == "RULE_04"
            assert res.override_verdict == "REJECTED"

        assert rule.evaluate({"location_country": "US"}) is None
        assert rule.evaluate({"location_country": "GB"}) is None

    def test_nocturnal_device_rule(self) -> None:
        rule = NocturnalDeviceRule(min_amount=2000.0, min_ratio=5.0)

        # Nocturnal (03:15 AM) + new device + high amount ($2,500)
        tx_hit = {
            "is_new_device": True,
            "amount": 2500.0,
            "timestamp": "2026-10-22T03:15:00+00:00",
        }
        res = rule.evaluate(tx_hit)
        assert res is not None
        assert res.rule_code == "RULE_05"
        assert res.override_verdict == "FLAGGED"

        # Not nocturnal (01:15 PM) -> None
        tx_day = {
            "is_new_device": True,
            "amount": 2500.0,
            "timestamp": "2026-10-22T13:15:00+00:00",
        }
        assert rule.evaluate(tx_day) is None

        # Not new device -> None
        tx_old = {
            "is_new_device": False,
            "amount": 2500.0,
            "timestamp": "2026-10-22T03:15:00+00:00",
        }
        assert rule.evaluate(tx_old) is None

        # Nocturnal + small amount but ratio >= 5.0 -> FLAGGED
        tx_ratio = {
            "is_new_device": True,
            "amount": 100.0,
            "timestamp": "2026-10-22T03:15:00+00:00",
        }
        res_ratio = rule.evaluate(tx_ratio, velocity={"amount_to_avg_ratio": 6.5})
        assert res_ratio is not None
        assert res_ratio.rule_code == "RULE_05"


class TestRuleEngineIntegration:
    """Verify consolidated rule orchestration and verdict prioritization."""

    def test_rule_engine_clean_transaction(self) -> None:
        engine = RuleEngine()
        tx = {
            "amount": 45.0,
            "location_country": "US",
            "is_new_device": False,
            "timestamp": "2026-10-22T15:00:00+00:00",
        }
        velocity = {"tx_count_1m": 1, "amount_to_avg_ratio": 1.0}
        result = engine.evaluate(tx, velocity)

        assert len(result.violations) == 0
        assert result.override_verdict is None
        assert result.total_penalty == 0.0
        assert not result.is_rejected
        assert not result.is_flagged

    def test_rule_engine_verdict_precedence(self) -> None:
        engine = RuleEngine()
        # Triggers both FLAGGED (RULE_02: amount > 25k) and REJECTED (RULE_04: IR)
        tx = {
            "amount": 30000.0,
            "location_country": "IR",
            "is_new_device": False,
            "timestamp": "2026-10-22T15:00:00+00:00",
        }
        result = engine.evaluate(tx)
        assert len(result.violations) == 2
        # REJECTED must take precedence over FLAGGED
        assert result.override_verdict == "REJECTED"
        assert result.is_rejected

    def test_inference_engine_score_transaction_integration(self) -> None:
        rule_engine = RuleEngine()
        inference_engine = InferenceEngine()

        # Clean transaction
        tx = {
            "transaction_id": f"tx_{uuid4().hex[:8]}",
            "user_id": str(uuid4()),
            "account_id": str(uuid4()),
            "amount": 25.0,
            "currency": "USD",
            "merchant_category": "grocery",
            "merchant_name": "Whole Foods",
            "location_country": "US",
            "is_foreign_transaction": False,
            "is_new_device": False,
            "timestamp": "2026-10-22T15:00:00+00:00",
        }
        rule_res = rule_engine.evaluate(tx)
        # Warm-up pass
        _ = inference_engine.score_transaction(tx, rule_result=rule_res)
        scored = inference_engine.score_transaction(tx, rule_result=rule_res)

        assert scored["status"] in ("APPROVED", "FLAGGED", "REJECTED")
        assert 0.0 <= scored["risk_score"] <= 1.0
        assert scored["latency_ms"] < 15.0

        # Hard rejected transaction via rule
        tx_sanctioned = dict(tx, location_country="KP")
        rule_res_rej = rule_engine.evaluate(tx_sanctioned)
        scored_rej = inference_engine.score_transaction(tx_sanctioned, rule_result=rule_res_rej)

        assert scored_rej["status"] == "REJECTED"
        assert scored_rej["risk_score"] == 1.0
        assert "RULE_04" in scored_rej["rule_violations"]
