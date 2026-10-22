"""Kafka Producer anomaly generator wrapper."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.streaming.anomalies import (
    ANOMALY_MERCHANTS,
    GEO_ANCHORS,
    AnomalyGenerator,
)

__all__ = ["ANOMALY_MERCHANTS", "GEO_ANCHORS", "AnomalyGenerator"]
