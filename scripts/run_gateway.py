"""
Standalone runner script for the Real-Time Fraud Detection Streaming Gateway.

Usage:
    python scripts/run_gateway.py --port 8000
    or
    uv run fraud-gateway --port 8000
"""

from pathlib import Path
import sys

# Ensure 'src' directory is in PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.api.app import main  # noqa: E402

if __name__ == "__main__":
    main()
