"""Top-level scripts/listen_alerts.py wrapper."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.streaming.listener import main, render_alert_card, run_listener  # noqa: E402

__all__ = ["main", "render_alert_card", "run_listener"]

if __name__ == "__main__":
    main()
