"""
Transaction event schema definition.

Validates inbound Kafka events using Pydantic V2.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class TransactionEvent(BaseModel):
    """Raw transaction event consumed from Kafka."""

    transaction_id: str = Field(..., description="Unique transaction idempotency identifier")
    user_id: UUID = Field(..., description="User UUID")
    account_id: UUID = Field(..., description="Account UUID")
    amount: float = Field(..., gt=0.0, description="Exact transaction monetary value in USD")
    currency: str = Field(
        default="USD", min_length=3, max_length=3, description="ISO 4217 Currency Code"
    )
    merchant_category: str = Field(
        ..., description="Merchant industry category (crypto, grocery, etc.)"
    )
    merchant_name: str = Field(..., description="Legal merchant name")
    location_country: str = Field(
        default="US", min_length=2, max_length=2, description="ISO 3166-1 alpha-2"
    )
    location_lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    location_lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    device_id: str | None = Field(default=None, description="Client hardware identifier")
    ip_address: str | None = Field(default=None, description="Originating client IP")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Event generation timestamp"
    )

    # Optional enrichment flags
    is_foreign_transaction: bool = False
    is_new_device: bool = False

    @field_validator("merchant_category")
    @classmethod
    def normalize_category(cls, v: str) -> str:
        return v.lower().strip()
