"""Top-level rule_engine module wrapper."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.rules.rule_engine import (
    SANCTIONED_COUNTRIES,
    BaseRule,
    HighValueThresholdRule,
    ImpossibleTravelRule,
    NocturnalDeviceRule,
    RuleEngine,
    RuleResult,
    RuleViolation,
    SanctionedCountryRule,
    VelocityBurstRule,
    calculate_haversine_distance_km,
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
