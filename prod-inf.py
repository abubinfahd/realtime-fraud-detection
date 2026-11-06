"""
Live Client Smoke Test for Azure ML Managed Online Endpoint.
Sends sample normal and fraudulent transactions to the deployed scoring URI.
"""

import json
import os
import urllib.request

# Read endpoint URL and API key from environment variables (or replace below for quick testing)
URL = os.getenv(
    "AZUREML_SCORING_URL",
    "https://fraud-live-fahd40.eastus.inference.ml.azure.com/score",
)
API_KEY = os.getenv("AZUREML_API_KEY", "<YOUR_PRIMARY_KEY>")


def invoke_endpoint() -> None:
    if API_KEY == "<YOUR_PRIMARY_KEY>":
        print("[!] Please set AZUREML_API_KEY environment variable or update API_KEY in prod-inf.py")
        return

    payload = {
        "data": [
            # Case 1: Normal legitimate transaction
            {
                "amount": 28.50,
                "hour_of_day": 14,
                "day_of_week": 2,
                "is_weekend": 0,
                "distance_from_home_km": 1.8,
                "velocity_1h": 1,
                "velocity_24h": 3,
                "avg_amount_24h": 32.0,
                "amount_to_avg_ratio": 0.89,
                "high_risk_mcc": 0,
            },
            # Case 2: High-risk midnight anomaly
            {
                "amount": 4850.00,
                "hour_of_day": 3,
                "day_of_week": 6,
                "is_weekend": 1,
                "distance_from_home_km": 920.0,
                "velocity_1h": 11,
                "velocity_24h": 28,
                "avg_amount_24h": 40.0,
                "amount_to_avg_ratio": 121.25,
                "high_risk_mcc": 1,
            },
        ]
    }

    body = str.encode(json.dumps(payload))
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    req = urllib.request.Request(URL, body, headers)
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode("utf-8"))
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    invoke_endpoint()
