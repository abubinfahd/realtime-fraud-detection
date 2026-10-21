"""
Transaction event schema definition.

Validates inbound Kafka events using Pydantic V2.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


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
    location_city: str | None = Field(default=None, description="City of transaction origin")
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

    @model_validator(mode="before")
    @classmethod
    def unpack_nested_fields(cls, data: Any) -> Any:
        """Unpack nested 'location' and 'device' sub-objects if present in payload."""
        if isinstance(data, dict):
            if "location" in data and isinstance(data["location"], dict):
                loc = data["location"]
                data.setdefault("location_country", loc.get("country", "US"))
                data.setdefault("location_city", loc.get("city"))
                data.setdefault("location_lat", loc.get("lat"))
                data.setdefault("location_lon", loc.get("lon"))
            if "device" in data and isinstance(data["device"], dict):
                dev = data["device"]
                data.setdefault("device_id", dev.get("device_id"))
                data.setdefault("ip_address", dev.get("ip_address"))
        return data

    @field_validator("merchant_category")
    @classmethod
    def normalize_category(cls, v: str) -> str:
        return v.lower().strip()

    def to_kafka_dict(self) -> dict[str, Any]:
        """Serialize event to canonical Kafka JSON structure with nested location/device."""
        return {
            "transaction_id": self.transaction_id,
            "user_id": str(self.user_id),
            "account_id": str(self.account_id),
            "amount": round(self.amount, 2),
            "currency": self.currency,
            "merchant_category": self.merchant_category,
            "merchant_name": self.merchant_name,
            "location": {
                "country": self.location_country,
                "city": self.location_city or "Unknown",
                "lat": self.location_lat,
                "lon": self.location_lon,
            },
            "device": {
                "device_id": self.device_id or "dev_unknown",
                "ip_address": self.ip_address or "127.0.0.1",
            },
            "timestamp": self.timestamp.isoformat(),
            "is_foreign_transaction": self.is_foreign_transaction,
            "is_new_device": self.is_new_device,
        }
