"""
Data loading and high-fidelity 10k transaction dataset generation.

Generates realistic financial transactions containing legitimate banking activity
and multi-modal fraud attack patterns (velocity testing, nocturnal account takeovers,
outlier spend spikes), serialized to data/raw/transactions_10k.csv.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from fraud_detection.core.config import settings
from fraud_detection.core.logger import get_logger

logger = get_logger(__name__)

MERCHANT_NAMES_BY_CATEGORY: dict[str, list[str]] = {
    "grocery": ["Whole Foods Market", "Trader Joe's", "Safeway", "Kroger", "Costco Wholesale"],
    "retail": ["Amazon.com", "Target", "Walmart", "Best Buy", "Nike Store"],
    "restaurants": ["Starbucks", "Chipotle Mexican Grill", "McDonald's", "Subway", "DoorDash"],
    "crypto": [
        "Binance Global",
        "Coinbase Pro",
        "Kraken Exchange",
        "KuCoin OTC",
        "Offshore Crypto Swap",
    ],
    "jewelry": ["Tiffany & Co.", "Kay Jewelers", "Luxury Watches Direct", "Blue Nile"],
    "electronics": ["Apple Store", "Micro Center", "Newegg", "B&H Photo Video"],
    "travel": ["Delta Air Lines", "United Airlines", "Airbnb", "Expedia", "Uber"],
    "entertainment": ["Netflix", "Spotify", "Steam Games", "PlayStation Network"],
    "gambling": ["BetMGM", "DraftKings Sportsbook", "Caesars Casino", "Offshore Poker Room"],
    "utilities": [
        "Pacific Gas & Electric",
        "AT&T Mobility",
        "Verizon Wireless",
        "Consolidated Edison",
    ],
}

US_CITIES: list[tuple[str, float, float]] = [
    ("New York", 40.7128, -74.0060),
    ("Los Angeles", 34.0522, -118.2437),
    ("Chicago", 41.8781, -87.6298),
    ("San Francisco", 37.7749, -122.4194),
    ("Miami", 25.7617, -80.1918),
    ("Seattle", 47.6062, -122.3321),
    ("Austin", 30.2672, -97.7431),
    ("Boston", 42.3601, -71.0589),
]

FOREIGN_CITIES: list[tuple[str, str, float, float]] = [
    ("George Town", "KY", 19.3133, -81.2546),
    ("London", "GB", 51.5074, -0.1278),
    ("Singapore", "SG", 1.3521, 103.8198),
    ("Dubai", "AE", 25.2048, 55.2708),
    ("Lagos", "NG", 6.5244, 3.3792),
]


def generate_10k_realistic_transactions(
    output_path: Path | str | None = None,
    n_samples: int = 10000,
    fraud_rate: float = 0.010,
    random_seed: int = 42,
) -> pd.DataFrame:
    """
    Generate 10,000 highly realistic financial transactions with 1.0% fraud prevalence.

    Parameters
    ----------
    output_path : Path | str | None
        Destination CSV path. Defaults to settings.DEMO_DATA_PATH.
    n_samples : int
        Total records to produce (default: 10,000).
    fraud_rate : float
        Fraud percentage (default: 0.01 = 1.0%).
    random_seed : int
        Reproducibility seed.

    Returns
    -------
    pd.DataFrame
        Complete DataFrame with 10k transactions.
    """
    np.random.seed(random_seed)
    n_fraud = int(n_samples * fraud_rate)  # 100
    n_legit = n_samples - n_fraud  # 9,900

    logger.info(
        "Generating 10k realistic transaction dataset",
        extra={"n_samples": n_samples, "n_legit": n_legit, "n_fraud": n_fraud},
    )

    # Deterministic user pool (500 users) including Stage 2 seed UUIDs
    known_user_ids = [
        "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
        "b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a22",
        "c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a33",
    ]
    random_users = [str(uuid4()) for _ in range(497)]
    user_pool = known_user_ids + random_users
    user_to_account = {uid: str(uuid4()) for uid in user_pool}

    # Reference timeline: 30 days up to now
    base_time = datetime.now(UTC) - timedelta(days=30)

    # -------------------------------------------------------------------------
    # 1. Legitimate Transactions (9,900 records)
    # -------------------------------------------------------------------------
    legit_users = np.random.choice(user_pool, size=n_legit)
    legit_accounts = [user_to_account[uid] for uid in legit_users]

    # Log-normal amounts: median ~$34, 95th percentile ~$115
    legit_amounts = np.round(np.random.lognormal(mean=3.5, sigma=0.82, size=n_legit), 2)
    legit_amounts = np.clip(legit_amounts, 2.50, 450.00)

    # Time distribution: normal daytime waking hours (8am - 10pm)
    hour_weights = [
        0.008,
        0.006,
        0.004,
        0.004,
        0.008,
        0.02,  # 00:00 - 05:00
        0.04,
        0.06,
        0.08,
        0.08,
        0.08,
        0.08,  # 06:00 - 11:00
        0.09,
        0.08,
        0.07,
        0.07,
        0.07,
        0.06,  # 12:00 - 17:00
        0.05,
        0.04,
        0.03,
        0.02,
        0.015,
        0.01,  # 18:00 - 23:00
    ]
    hour_probs = np.array(hour_weights, dtype=float)
    hour_probs = hour_probs / hour_probs.sum()
    legit_hours = np.random.choice(np.arange(24), size=n_legit, p=hour_probs)
    random_days = np.random.randint(0, 30, size=n_legit)
    random_minutes = np.random.randint(0, 60, size=n_legit)
    random_seconds = np.random.randint(0, 60, size=n_legit)

    legit_timestamps = [
        (
            base_time + timedelta(days=int(d), hours=int(h), minutes=int(m), seconds=int(s))
        ).isoformat()
        for d, h, m, s in zip(random_days, legit_hours, random_minutes, random_seconds)
    ]

    legit_categories = [
        "grocery",
        "retail",
        "restaurants",
        "utilities",
        "entertainment",
        "travel",
        "electronics",
        "crypto",
        "jewelry",
        "gambling",
    ]
    legit_cat_probs = [0.26, 0.24, 0.22, 0.08, 0.08, 0.05, 0.04, 0.01, 0.01, 0.01]
    assigned_legit_cats = np.random.choice(legit_categories, size=n_legit, p=legit_cat_probs)
    assigned_legit_merchants = [
        np.random.choice(MERCHANT_NAMES_BY_CATEGORY[c]) for c in assigned_legit_cats
    ]

    city_indices = np.random.choice(len(US_CITIES), size=n_legit)
    legit_cities = [US_CITIES[i][0] for i in city_indices]
    legit_lats = [US_CITIES[i][1] for i in city_indices]
    legit_lons = [US_CITIES[i][2] for i in city_indices]
    legit_countries = ["US"] * n_legit

    # Redis sliding window features simulation
    legit_tx_1m = np.random.choice([1, 2, 3], size=n_legit, p=[0.92, 0.06, 0.02])
    legit_tx_10m = legit_tx_1m + np.random.choice([0, 1, 2], size=n_legit, p=[0.78, 0.18, 0.04])
    legit_sum_10m = np.round(
        legit_amounts * legit_tx_10m * np.random.uniform(0.9, 1.15, size=n_legit), 2
    )
    legit_ratios = np.round(legit_amounts / (legit_sum_10m / np.maximum(legit_tx_10m, 1)), 2)

    legit_foreign = np.zeros(n_legit, dtype=int)
    legit_new_device = np.random.choice([0, 1], size=n_legit, p=[0.95, 0.05])
    legit_device_ids = [f"dev_{uuid4().hex[:12]}" for _ in range(n_legit)]
    legit_ips = [
        f"192.168.{np.random.randint(1, 254)}.{np.random.randint(1, 254)}" for _ in range(n_legit)
    ]

    df_legit = pd.DataFrame(
        {
            "transaction_id": [f"tx_{uuid4()}" for _ in range(n_legit)],
            "user_id": legit_users,
            "account_id": legit_accounts,
            "amount": legit_amounts,
            "currency": "USD",
            "merchant_category": assigned_legit_cats,
            "merchant_name": assigned_legit_merchants,
            "location_country": legit_countries,
            "location_city": legit_cities,
            "location_lat": legit_lats,
            "location_lon": legit_lons,
            "device_id": legit_device_ids,
            "ip_address": legit_ips,
            "timestamp": legit_timestamps,
            "tx_count_1m": legit_tx_1m,
            "tx_count_10m": legit_tx_10m,
            "tx_sum_10m": legit_sum_10m,
            "amount_to_avg_ratio": legit_ratios,
            "is_foreign_transaction": legit_foreign,
            "is_new_device": legit_new_device,
            "is_fraud": 0,
        }
    )

    # -------------------------------------------------------------------------
    # 2. Fraudulent Transactions (100 records - 1.0%)
    # -------------------------------------------------------------------------
    # 40% Velocity Bot Testing (micro amounts, 8-15 tx/60s)
    nA = int(n_fraud * 0.40)  # 40
    # 60% High-Value Account Takeover (crypto, luxury, nocturnal)
    nB = n_fraud - nA  # 60

    fraud_users = np.random.choice(user_pool, size=n_fraud)
    fraud_accounts = [user_to_account[uid] for uid in fraud_users]

    # Pattern A: Micro-charge card testing
    fraud_A_amt = np.round(np.random.uniform(1.25, 9.99, size=nA), 2)
    fraud_A_hours = np.random.randint(0, 24, size=nA)
    fraud_A_cats = np.random.choice(["electronics", "retail", "utilities"], size=nA)
    fraud_A_merchants = [np.random.choice(MERCHANT_NAMES_BY_CATEGORY[c]) for c in fraud_A_cats]
    fraud_A_tx_1m = np.random.randint(7, 16, size=nA)
    fraud_A_tx_10m = fraud_A_tx_1m + np.random.randint(6, 18, size=nA)
    fraud_A_sum_10m = np.round(fraud_A_amt * fraud_A_tx_10m * 1.3, 2)
    fraud_A_ratios = np.round(fraud_A_amt / (fraud_A_sum_10m / np.maximum(fraud_A_tx_10m, 1)), 2)
    fraud_A_foreign = np.random.choice([0, 1], size=nA, p=[0.5, 0.5])
    fraud_A_new_device = np.ones(nA, dtype=int)

    # Pattern B: High-Value Nocturnal Account Takeover
    fraud_B_amt = np.round(np.random.uniform(1200.0, 4999.0, size=nB), 2)
    fraud_B_hours = np.random.choice([1, 2, 3, 4], size=nB)  # 1am - 4am
    fraud_B_cats = np.random.choice(["crypto", "jewelry", "gambling"], size=nB)
    fraud_B_merchants = [np.random.choice(MERCHANT_NAMES_BY_CATEGORY[c]) for c in fraud_B_cats]
    fraud_B_tx_1m = np.random.choice([1, 2, 3], size=nB)
    fraud_B_tx_10m = np.random.randint(2, 6, size=nB)
    fraud_B_sum_10m = np.round(fraud_B_amt + np.random.uniform(50.0, 150.0, size=nB), 2)
    fraud_B_ratios = np.round(np.random.uniform(5.5, 14.0, size=nB), 2)
    fraud_B_foreign = np.random.choice([0, 1], size=nB, p=[0.2, 0.8])
    fraud_B_new_device = np.ones(nB, dtype=int)

    # Assemble fraud metadata
    fraud_amts = np.concatenate([fraud_A_amt, fraud_B_amt])
    fraud_hours = np.concatenate([fraud_A_hours, fraud_B_hours])
    fraud_cats = np.concatenate([fraud_A_cats, fraud_B_cats])
    fraud_merchants = fraud_A_merchants + fraud_B_merchants
    fraud_tx_1m = np.concatenate([fraud_A_tx_1m, fraud_B_tx_1m])
    fraud_tx_10m = np.concatenate([fraud_A_tx_10m, fraud_B_tx_10m])
    fraud_sums_10m = np.concatenate([fraud_A_sum_10m, fraud_B_sum_10m])
    fraud_ratios = np.concatenate([fraud_A_ratios, fraud_B_ratios])
    fraud_foreigns = np.concatenate([fraud_A_foreign, fraud_B_foreign])
    fraud_new_devices = np.concatenate([fraud_A_new_device, fraud_B_new_device])

    fraud_timestamps = [
        (
            base_time
            + timedelta(
                days=int(np.random.randint(0, 30)),
                hours=int(h),
                minutes=int(np.random.randint(0, 60)),
            )
        ).isoformat()
        for h in fraud_hours
    ]

    # Geolocation for fraud: mix of US and foreign tax haven / offshore hubs
    fraud_cities: list[str] = []
    fraud_countries: list[str] = []
    fraud_lats: list[float] = []
    fraud_lons: list[float] = []

    for is_f in fraud_foreigns:
        if is_f == 1:
            city, country, lat, lon = FOREIGN_CITIES[np.random.randint(len(FOREIGN_CITIES))]
        else:
            city, lat, lon = US_CITIES[np.random.randint(len(US_CITIES))]
            country = "US"
        fraud_cities.append(city)
        fraud_countries.append(country)
        fraud_lats.append(lat)
        fraud_lons.append(lon)

    df_fraud = pd.DataFrame(
        {
            "transaction_id": [f"tx_{uuid4()}" for _ in range(n_fraud)],
            "user_id": fraud_users,
            "account_id": fraud_accounts,
            "amount": fraud_amts,
            "currency": "USD",
            "merchant_category": fraud_cats,
            "merchant_name": fraud_merchants,
            "location_country": fraud_countries,
            "location_city": fraud_cities,
            "location_lat": fraud_lats,
            "location_lon": fraud_lons,
            "device_id": [f"dev_{uuid4().hex[:12]}" for _ in range(n_fraud)],
            "ip_address": [
                f"198.51.{np.random.randint(1, 254)}.{np.random.randint(1, 254)}"
                for _ in range(n_fraud)
            ],
            "timestamp": fraud_timestamps,
            "tx_count_1m": fraud_tx_1m,
            "tx_count_10m": fraud_tx_10m,
            "tx_sum_10m": fraud_sums_10m,
            "amount_to_avg_ratio": fraud_ratios,
            "is_foreign_transaction": fraud_foreigns,
            "is_new_device": fraud_new_devices,
            "is_fraud": 1,
        }
    )

    # Combine, shuffle, and save
    df = pd.concat([df_legit, df_fraud], ignore_index=True)
    df = df.sample(frac=1.0, random_state=random_seed).reset_index(drop=True)

    dest = Path(output_path or settings.DEMO_DATA_PATH)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    logger.info("Demo dataset successfully generated", extra={"path": str(dest), "rows": len(df)})

    return df


def load_or_generate_dataset(
    filepath: Path | str | None = None,
    force_regenerate: bool = False,
) -> pd.DataFrame:
    """
    Load dataset from CSV if it exists; otherwise generate and save it.

    Parameters
    ----------
    filepath : Path | str | None
        Path to CSV file. Defaults to settings.DEMO_DATA_PATH.
    force_regenerate : bool
        If True, regenerates the dataset regardless of file presence.

    Returns
    -------
    pd.DataFrame
        Loaded transaction dataset.
    """
    path = Path(filepath or settings.DEMO_DATA_PATH)

    if path.exists() and not force_regenerate:
        logger.info("Loading existing dataset from CSV", extra={"path": str(path)})
        df = pd.read_csv(path)
        logger.info(
            "Dataset loaded",
            extra={"rows": len(df), "fraud_count": int(df["is_fraud"].sum())},
        )
        return df

    return generate_10k_realistic_transactions(output_path=path)


# Backwards compatibility alias
generate_synthetic_transactions = generate_10k_realistic_transactions
