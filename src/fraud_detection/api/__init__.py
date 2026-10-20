"""API package exposing FastAPI application factory."""

from fraud_detection.api.app import create_app

__all__ = ["create_app"]
