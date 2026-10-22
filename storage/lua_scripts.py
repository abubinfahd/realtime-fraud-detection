"""Top-level storage lua_scripts wrapper."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.storage.lua_scripts import (
    GET_VELOCITY_READ_SCRIPT,
    SLIDING_WINDOW_INGEST_SCRIPT,
)

__all__ = [
    "GET_VELOCITY_READ_SCRIPT",
    "SLIDING_WINDOW_INGEST_SCRIPT",
]
