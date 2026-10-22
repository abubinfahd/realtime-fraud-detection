"""Top-level consumers/persistence_worker.py wrapper."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fraud_detection.streaming.persistence_buffer import (  # noqa: E402
    PersistenceBuffer,
    main,
    run_persistence_demo,
)

__all__ = ["PersistenceBuffer", "main", "run_persistence_demo"]

if __name__ == "__main__":
    main()
