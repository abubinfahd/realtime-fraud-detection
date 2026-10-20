"""
Real-Time Fraud Detection System — Primary FastAPI Entry Point.

Starts the Uvicorn ASGI server hosting the real-time inference API,
health checks, Swagger UI documentation, and WebSocket streaming gateway.

Usage:
    uv run uvicorn main:app --reload --port 8000
    or
    uv run python main.py
"""

import sys
from pathlib import Path

# Ensure 'src' directory is present in module search path
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import uvicorn  # noqa: E402

from fraud_detection.api.app import create_app  # noqa: E402

# Instantiate top-level ASGI application
app = create_app()


def main() -> None:
    """Launch Uvicorn development server."""
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
