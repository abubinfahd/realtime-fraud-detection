"""Top-level api/websocket_manager.py wrapper."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.api.websocket_manager import ConnectionManager, manager  # noqa: E402

__all__ = ["ConnectionManager", "manager"]
