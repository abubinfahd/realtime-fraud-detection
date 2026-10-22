"""Top-level schemas package wrapper."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.schemas.alert import (
    AlertSignals,
    FraudAlert,
    FraudAlertEvent,
    VelocityContext,
)
from fraud_detection.schemas.transaction import TransactionEvent

__all__ = [
    "AlertSignals",
    "FraudAlert",
    "FraudAlertEvent",
    "TransactionEvent",
    "VelocityContext",
]
