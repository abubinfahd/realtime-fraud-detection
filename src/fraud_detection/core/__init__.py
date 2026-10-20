"""Core utilities: configuration and logging."""

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger

__all__ = ["get_logger", "settings"]
