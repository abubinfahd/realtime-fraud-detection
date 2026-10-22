"""
Fraud alert schema definition.

Used for broadcasting high-risk alerts over Redis Pub/Sub to WebSockets.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AlertSignals(BaseModel):
    """Explainability signals justifying the fraud decision."""

    lgbm_fraud_prob: float = Field(..., ge=0.0, le=1.0)
    anomaly_score: float = Field(..., ge=0.0, le=1.0)
    rule_violations: list[str] = Field(default_factory=list)


class VelocityContext(BaseModel):
    """Point-in-time velocity signals from Redis."""

    tx_count_1m: int
    tx_count_10m: int
    tx_sum_10m: float
    amount_to_avg_ratio: float


class FraudAlert(BaseModel):
    """High-risk alert payload published to Redis channel:fraud-alerts."""

    event_type: str = "FRAUD_ALERT"
    transaction_id: str
    user_id: UUID
    amount: float
    currency: str = "USD"
    status: str  # FLAGGED or REJECTED
    risk_score: float = Field(..., ge=0.0, le=1.0)
    merchant_name: str
    merchant_category: str
    signals: AlertSignals
    velocity_context: VelocityContext
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    inference_latency_ms: float


class FraudAlertEvent(BaseModel):
    """High-risk fraud alert event model for alerts processing."""

    alert_id: str
    transaction_id: str
    user_id: UUID
    account_id: UUID
    amount: float = Field(..., gt=0)
    currency: str = "USD"
    merchant_name: str
    merchant_category: str
    fraud_probability: float = Field(..., ge=0.0, le=1.0)
    anomaly_score: float = Field(..., ge=0.0, le=1.0)
    risk_score: float = Field(..., ge=0.0, le=1.0)
    decision: str
    reasons: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


__all__ = [
    "AlertSignals",
    "FraudAlert",
    "FraudAlertEvent",
    "VelocityContext",
]
