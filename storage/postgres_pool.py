"""Top-level storage/postgres_pool.py wrapper."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.storage.postgres_pool import (  # noqa: E402
    InMemoryPostgresConnection,
    InMemoryPostgresPool,
    PostgresPool,
)

__all__ = [
    "InMemoryPostgresConnection",
    "InMemoryPostgresPool",
    "PostgresPool",
]
