"""Deterministic Rule Engine for Real-Time Fraud and Compliance Overrides.

Evaluates high-speed business guardrails that can directly trigger FLAGGED
or REJECTED overrides, or supply penalty scores to composite risk scoring.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fraud_detection.ml.preprocessing import parse_timestamp

# International sanctions blacklist (OFAC high-risk / sanctioned jurisdictions)
SANCTIONED_COUNTRIES: set[str] = {"IR", "KP", "SY", "CU"}


def calculate_haversine_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Calculate great-circle distance between two coordinates in kilometers."""
    r = 6371.0  # Earth's mean radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


@dataclass(frozen=True)
class RuleViolation:
    """Structured record of a single triggered deterministic rule."""

    rule_code: str
    name: str
    description: str
    override_verdict: str | None  # "REJECTED", "FLAGGED", or None
    penalty_score: float = 0.0


@dataclass
class RuleResult:
    """Consolidated outcome of evaluating all deterministic rules."""

    violations: list[RuleViolation] = field(default_factory=list)
    override_verdict: str | None = None
    total_penalty: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def is_rejected(self) -> bool:
        """Return True if any rule mandated a hard REJECTED override."""
        return self.override_verdict == "REJECTED"

    @property
    def is_flagged(self) -> bool:
        """Return True if a rule mandated a FLAGGED review override."""
        return self.override_verdict == "FLAGGED"


class BaseRule:
    """Abstract base class for all deterministic fraud rules."""

    rule_code: str
    name: str

    def evaluate(
        self,
        transaction: Mapping[str, Any],
        velocity: Mapping[str, Any] | None = None,
        last_location: Mapping[str, Any] | None = None,
    ) -> RuleViolation | None:
        """Evaluate the rule against transaction and context signals."""
        raise NotImplementedError


class VelocityBurstRule(BaseRule):
    """RULE_01: Automated card testing / bot velocity burst (tx_count_1m >= 8)."""

    rule_code = "RULE_01"
    name = "Velocity Burst"

    def __init__(self, threshold_count: int = 8) -> None:
        self.threshold_count = threshold_count

    def evaluate(
        self,
        transaction: Mapping[str, Any],
        velocity: Mapping[str, Any] | None = None,
        last_location: Mapping[str, Any] | None = None,
    ) -> RuleViolation | None:
        if velocity is None:
            return None
        tx_count_1m = int(velocity.get("tx_count_1m", 1))
        if tx_count_1m >= self.threshold_count:
            return RuleViolation(
                rule_code=self.rule_code,
                name=self.name,
                description=(
                    f"Automated card testing / bot velocity burst: {tx_count_1m} tx/min "
                    f"(threshold >= {self.threshold_count})"
                ),
                override_verdict="REJECTED",
                penalty_score=1.0,
            )
        return None


class HighValueThresholdRule(BaseRule):
    """RULE_02: High-value single charge threshold (amount >= $25,000.00)."""

    rule_code = "RULE_02"
    name = "High-Value Single Charge"

    def __init__(self, threshold_amount: float = 25000.0) -> None:
        self.threshold_amount = threshold_amount

    def evaluate(
        self,
        transaction: Mapping[str, Any],
        velocity: Mapping[str, Any] | None = None,
        last_location: Mapping[str, Any] | None = None,
    ) -> RuleViolation | None:
        amount = float(transaction.get("amount", 0.0))
        if amount >= self.threshold_amount:
            return RuleViolation(
                rule_code=self.rule_code,
                name=self.name,
                description=(
                    f"High-value single charge threshold exceeded: ${amount:,.2f} "
                    f"(threshold >= ${self.threshold_amount:,.2f})"
                ),
                override_verdict="FLAGGED",
                penalty_score=0.35,
            )
        return None


class ImpossibleTravelRule(BaseRule):
    """RULE_03: Geographic impossibility / travel speed > 900 km/h."""

    rule_code = "RULE_03"
    name = "Impossible Travel"

    def __init__(
        self,
        max_speed_kmh: float = 900.0,
        min_distance_km: float = 50.0,
    ) -> None:
        self.max_speed_kmh = max_speed_kmh
        self.min_distance_km = min_distance_km

    def evaluate(
        self,
        transaction: Mapping[str, Any],
        velocity: Mapping[str, Any] | None = None,
        last_location: Mapping[str, Any] | None = None,
    ) -> RuleViolation | None:
        if last_location is None:
            return None

        # Extract current coordinates
        curr_lat = transaction.get("location_lat")
        curr_lon = transaction.get("location_lon")
        if curr_lat is None or curr_lon is None:
            return None

        # Extract previous coordinates
        prev_lat = last_location.get("lat")
        prev_lon = last_location.get("lon")
        if prev_lat is None or prev_lon is None:
            return None

        # Calculate physical distance
        dist_km = calculate_haversine_distance_km(
            float(prev_lat),
            float(prev_lon),
            float(curr_lat),
            float(curr_lon),
        )

        if dist_km < self.min_distance_km:
            return None

        # Calculate time delta in hours
        curr_dt = parse_timestamp(transaction.get("timestamp"))
        curr_ts_s = curr_dt.timestamp()

        prev_ts = last_location.get("timestamp_ms")
        if prev_ts is not None:
            prev_ts_s = float(prev_ts) / 1000.0 if prev_ts > 1e11 else float(prev_ts)
        else:
            prev_ts_s = curr_ts_s

        elapsed_s = abs(curr_ts_s - prev_ts_s)
        elapsed_hours = elapsed_s / 3600.0

        if elapsed_hours <= (1.0 / 3600.0):  # less than 1 second
            speed_kmh = 999999.0
        else:
            speed_kmh = dist_km / elapsed_hours

        if speed_kmh > self.max_speed_kmh:
            return RuleViolation(
                rule_code=self.rule_code,
                name=self.name,
                description=(
                    f"Geographic impossibility: calculated speed {speed_kmh:.1f} km/h "
                    f"exceeds limit {self.max_speed_kmh:.1f} km/h over {dist_km:.1f} km "
                    f"in {elapsed_s:.1f}s"
                ),
                override_verdict="REJECTED",
                penalty_score=1.0,
            )
        return None


class SanctionedCountryRule(BaseRule):
    """RULE_04: Regulatory compliance / OFAC sanctioned jurisdiction."""

    rule_code = "RULE_04"
    name = "Sanctioned Country"

    def __init__(self, sanctioned_countries: set[str] | None = None) -> None:
        self.sanctioned_countries = sanctioned_countries or SANCTIONED_COUNTRIES

    def evaluate(
        self,
        transaction: Mapping[str, Any],
        velocity: Mapping[str, Any] | None = None,
        last_location: Mapping[str, Any] | None = None,
    ) -> RuleViolation | None:
        country = str(transaction.get("location_country") or "").upper().strip()
        if country in self.sanctioned_countries:
            return RuleViolation(
                rule_code=self.rule_code,
                name=self.name,
                description=(
                    f"Regulatory compliance violation: jurisdiction '{country}' is in the "
                    f"sanctioned countries list"
                ),
                override_verdict="REJECTED",
                penalty_score=1.0,
            )
        return None


class NocturnalDeviceRule(BaseRule):
    """RULE_05: High-risk nocturnal account takeover (New device + 2:00-4:30 AM + high value)."""

    rule_code = "RULE_05"
    name = "Nocturnal Account Takeover"

    def __init__(
        self,
        min_amount: float = 2000.0,
        min_ratio: float = 5.0,
    ) -> None:
        self.min_amount = min_amount
        self.min_ratio = min_ratio

    def evaluate(
        self,
        transaction: Mapping[str, Any],
        velocity: Mapping[str, Any] | None = None,
        last_location: Mapping[str, Any] | None = None,
    ) -> RuleViolation | None:
        is_new_device = bool(transaction.get("is_new_device", False))
        if not is_new_device:
            return None

        dt = parse_timestamp(transaction.get("timestamp"))
        hour = dt.hour
        minute = dt.minute

        # Between 02:00 and 04:30
        is_nocturnal = (hour in (2, 3)) or (hour == 4 and minute <= 30)
        if not is_nocturnal:
            return None

        amount = float(transaction.get("amount", 0.0))
        ratio = float(velocity.get("amount_to_avg_ratio", 1.0)) if velocity else 1.0

        if amount >= self.min_amount or ratio >= self.min_ratio:
            return RuleViolation(
                rule_code=self.rule_code,
                name=self.name,
                description=(
                    f"Nocturnal account takeover pattern: new device active at "
                    f"{hour:02d}:{minute:02d} with amount=${amount:,.2f} (ratio={ratio:.1f})"
                ),
                override_verdict="FLAGGED",
                penalty_score=0.30,
            )
        return None


class RuleEngine:
    """Orchestrates deterministic rule evaluations across transactions."""

    def __init__(self, rules: list[BaseRule] | None = None) -> None:
        self.rules: list[BaseRule] = (
            rules
            if rules is not None
            else [
                VelocityBurstRule(),
                HighValueThresholdRule(),
                ImpossibleTravelRule(),
                SanctionedCountryRule(),
                NocturnalDeviceRule(),
            ]
        )

    def evaluate(
        self,
        transaction: Mapping[str, Any],
        velocity: Mapping[str, Any] | None = None,
        last_location: Mapping[str, Any] | None = None,
    ) -> RuleResult:
        """Run all configured rules and build the composite RuleResult."""
        violations: list[RuleViolation] = []
        override_verdict: str | None = None
        total_penalty = 0.0
        reasons: list[str] = []

        for rule in self.rules:
            violation = rule.evaluate(
                transaction=transaction,
                velocity=velocity,
                last_location=last_location,
            )
            if violation is not None:
                violations.append(violation)
                reasons.append(f"[{violation.rule_code}] {violation.description}")
                total_penalty += violation.penalty_score

                # Determine strictest verdict: REJECTED > FLAGGED
                if violation.override_verdict == "REJECTED":
                    override_verdict = "REJECTED"
                elif violation.override_verdict == "FLAGGED" and override_verdict != "REJECTED":
                    override_verdict = "FLAGGED"

        return RuleResult(
            violations=violations,
            override_verdict=override_verdict,
            total_penalty=round(min(total_penalty, 1.0), 4),
            reasons=reasons,
        )


__all__ = [
    "SANCTIONED_COUNTRIES",
    "BaseRule",
    "HighValueThresholdRule",
    "ImpossibleTravelRule",
    "NocturnalDeviceRule",
    "RuleEngine",
    "RuleResult",
    "RuleViolation",
    "SanctionedCountryRule",
    "VelocityBurstRule",
    "calculate_haversine_distance_km",
]
