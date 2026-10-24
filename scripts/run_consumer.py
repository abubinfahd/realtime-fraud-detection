"""CLI runner script for real-time Kafka fraud detection consumer worker."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.streaming.consumer import main  # noqa: E402

if __name__ == "__main__":
    main()
