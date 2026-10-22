"""Top-level consumers/fraud_consumer.py wrapper."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.streaming.consumer import FraudConsumer, main

__all__ = ["FraudConsumer", "main"]

if __name__ == "__main__":
    main()
