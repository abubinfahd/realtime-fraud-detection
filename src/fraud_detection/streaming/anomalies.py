"""Synthetic Anomaly and Fraud Pattern Generators.

Generates realistic attack distributions:
1. Velocity Spike Attack (Card testing micro-charges)
2. Sudden High-Value Outlier (Account Takeover in crypto/luxury)
3. Geographic Impossibility (Impossible travel speed across continents)
4. Nocturnal High-Risk Category (Offshore crypto/gambling in early morning hours)
"""

import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fraud_detection.schemas.transaction import TransactionEvent

# Known high-risk and legitimate merchant mappings
ANOMALY_MERCHANTS = {
    "crypto": ["Binance Global", "Coinbase Pro", "Kraken Exchange", "KuCoin", "Bybit"],
    "jewelry": ["Tiffany & Co.", "Cartier", "Kay Jewelers", "Zales", "Harry Winston"],
    "gambling": ["BetMGM", "DraftKings", "FanDuel", "Bovada", "Caesars Sportsbook"],
    "electronics": ["Micro Center", "Apple Store", "B&H Photo Video", "Newegg"],
    "retail": ["Target", "Amazon Web Store", "Walmart Express", "Best Buy"],
    "utilities": ["AT&T Digital", "Verizon Pay", "Spectrum Online"],
}

# Geolocation anchors for impossible travel anomalies
GEO_ANCHORS = {
    "tokyo": {"country": "JP", "city": "Tokyo", "lat": 35.6762, "lon": 139.6503},
    "london": {"country": "GB", "city": "London", "lat": 51.5074, "lon": -0.1278},
    "new_york": {"country": "US", "city": "New York", "lat": 40.7128, "lon": -74.0060},
    "sydney": {"country": "AU", "city": "Sydney", "lat": -33.8688, "lon": 151.2093},
    "dubai": {"country": "AE", "city": "Dubai", "lat": 25.2048, "lon": 55.2708},
}


class AnomalyGenerator:
    """Stateful or functional generator for distinct fraud attack patterns."""

    @staticmethod
    def generate_velocity_spike(
        user_id: UUID,
        account_id: UUID,
        base_timestamp: datetime | None = None,
        burst_size: int | None = None,
    ) -> list[TransactionEvent]:
        """Pattern 1: Velocity Spike Attack (Card Testing).

        Generates 8-15 rapid micro-transactions ($1.00 - $5.00) within 15-20 seconds.
        """
        now = base_timestamp or datetime.now(UTC)
        count = burst_size or random.randint(8, 15)
        events: list[TransactionEvent] = []

        online_cats = ["retail", "utilities", "electronics"]
        attacker_device = f"dev_botnet_{uuid4().hex[:10]}"
        attacker_ip = f"198.51.{random.randint(10, 200)}.{random.randint(2, 250)}"

        for i in range(count):
            cat = random.choice(online_cats)
            merchant = random.choice(ANOMALY_MERCHANTS[cat])
            amt = round(random.uniform(1.00, 5.00), 2)
            event_ts = now + timedelta(seconds=i * random.uniform(1.0, 1.8))

            events.append(
                TransactionEvent(
                    transaction_id=f"tx_spike_{uuid4().hex[:12]}",
                    user_id=user_id,
                    account_id=account_id,
                    amount=amt,
                    currency="USD",
                    merchant_category=cat,
                    merchant_name=merchant,
                    location_country="US",
                    location_city="Online Gateway",
                    location_lat=40.7128,
                    location_lon=-74.0060,
                    device_id=attacker_device,
                    ip_address=attacker_ip,
                    timestamp=event_ts,
                    is_foreign_transaction=False,
                    is_new_device=True,
                )
            )

        return events

    @staticmethod
    def generate_high_value_outlier(
        user_id: UUID,
        account_id: UUID,
        timestamp: datetime | None = None,
    ) -> TransactionEvent:
        """Pattern 2: Sudden High-Value Outlier (Account Takeover).

        A user submits a single large purchase ($1,200 - $4,999) at crypto/luxury merchant.
        """
        now = timestamp or datetime.now(UTC)
        cat = random.choice(["crypto", "jewelry", "electronics"])
        merchant = random.choice(ANOMALY_MERCHANTS[cat])
        amt = round(random.uniform(1200.00, 4999.00), 2)

        return TransactionEvent(
            transaction_id=f"tx_highval_{uuid4().hex[:12]}",
            user_id=user_id,
            account_id=account_id,
            amount=amt,
            currency="USD",
            merchant_category=cat,
            merchant_name=merchant,
            location_country="US",
            location_city="Miami",
            location_lat=25.7617,
            location_lon=-80.1918,
            device_id=f"dev_ato_{uuid4().hex[:10]}",
            ip_address=f"203.0.113.{random.randint(1, 250)}",
            timestamp=now,
            is_foreign_transaction=False,
            is_new_device=True,
        )

    @staticmethod
    def generate_geographic_jump(
        user_id: UUID,
        account_id: UUID,
        timestamp: datetime | None = None,
    ) -> tuple[TransactionEvent, TransactionEvent]:
        """Pattern 3: Geographic Impossibility (Impossible Travel).

        Emits two physical transactions separated by thousands of kilometers within 2-5 minutes.
        Example: Tokyo then London (>9,500 km displacement in 300 seconds).
        """
        t1_time = timestamp or datetime.now(UTC)
        t2_time = t1_time + timedelta(seconds=random.randint(120, 300))  # 2 to 5 minutes later

        tokyo = GEO_ANCHORS["tokyo"]
        london = GEO_ANCHORS["london"]

        # Legitimate card-present charge in Tokyo
        tx1 = TransactionEvent(
            transaction_id=f"tx_geo1_{uuid4().hex[:12]}",
            user_id=user_id,
            account_id=account_id,
            amount=round(random.uniform(25.00, 85.00), 2),
            currency="USD",
            merchant_category="retail",
            merchant_name="Tokyo Ginza Retail",
            location_country=tokyo["country"],
            location_city=tokyo["city"],
            location_lat=tokyo["lat"],
            location_lon=tokyo["lon"],
            device_id=f"dev_pos_{uuid4().hex[:8]}",
            ip_address=f"133.242.{random.randint(1, 250)}.{random.randint(1, 250)}",
            timestamp=t1_time,
            is_foreign_transaction=True,
            is_new_device=False,
        )

        # Impossible card-present charge in London
        tx2 = TransactionEvent(
            transaction_id=f"tx_geo2_{uuid4().hex[:12]}",
            user_id=user_id,
            account_id=account_id,
            amount=round(random.uniform(450.00, 1850.00), 2),
            currency="USD",
            merchant_category="jewelry",
            merchant_name="Harrods Luxury London",
            location_country=london["country"],
            location_city=london["city"],
            location_lat=london["lat"],
            location_lon=london["lon"],
            device_id=f"dev_pos_{uuid4().hex[:8]}",
            ip_address=f"82.165.{random.randint(1, 250)}.{random.randint(1, 250)}",
            timestamp=t2_time,
            is_foreign_transaction=True,
            is_new_device=True,
        )

        return tx1, tx2

    @staticmethod
    def generate_nocturnal_high_risk(
        user_id: UUID,
        account_id: UUID,
        timestamp: datetime | None = None,
    ) -> TransactionEvent:
        """Pattern 4: Nocturnal High-Risk Category.

        Initiated between 2:00 AM and 4:30 AM local time targeting offshore crypto or gambling.
        """
        now = timestamp or datetime.now(UTC)
        # Force hour to 02:00 - 04:30
        nocturnal_time = now.replace(
            hour=random.randint(2, 4),
            minute=random.randint(0, 30),
            second=random.randint(0, 59),
        )

        cat = random.choice(["crypto", "gambling"])
        merchant = random.choice(ANOMALY_MERCHANTS[cat])
        amt = round(random.uniform(450.00, 2400.00), 2)
        dubai = GEO_ANCHORS["dubai"]

        return TransactionEvent(
            transaction_id=f"tx_nocturnal_{uuid4().hex[:12]}",
            user_id=user_id,
            account_id=account_id,
            amount=amt,
            currency="USD",
            merchant_category=cat,
            merchant_name=merchant,
            location_country=dubai["country"],
            location_city=dubai["city"],
            location_lat=dubai["lat"],
            location_lon=dubai["lon"],
            device_id=f"dev_nocturnal_{uuid4().hex[:10]}",
            ip_address=f"185.190.{random.randint(1, 250)}.{random.randint(1, 250)}",
            timestamp=nocturnal_time,
            is_foreign_transaction=True,
            is_new_device=True,
        )

    @classmethod
    def generate_random_anomaly(
        cls,
        user_id: UUID,
        account_id: UUID,
        timestamp: datetime | None = None,
    ) -> list[TransactionEvent]:
        """Pick one of the 4 anomaly topologies at random."""
        choice = random.choice([1, 2, 3, 4])
        if choice == 1:
            return cls.generate_velocity_spike(user_id, account_id, timestamp)
        elif choice == 2:
            return [cls.generate_high_value_outlier(user_id, account_id, timestamp)]
        elif choice == 3:
            t1, t2 = cls.generate_geographic_jump(user_id, account_id, timestamp)
            return [t1, t2]
        else:
            return [cls.generate_nocturnal_high_risk(user_id, account_id, timestamp)]


__all__ = ["ANOMALY_MERCHANTS", "GEO_ANCHORS", "AnomalyGenerator"]
