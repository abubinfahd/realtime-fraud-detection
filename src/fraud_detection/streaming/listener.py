"""Real-time Fraud Alerts Pub/Sub Listener Service.

Subscribes to Redis Pub/Sub channels (channel:fraud-alerts and channel:system-metrics)
and formats real-time threat intelligence cards.
"""

import argparse
import asyncio
import signal

from fraud_detection.core.config import settings
from fraud_detection.storage.redis_publisher import RedisPublisher


def render_alert_card(alert: dict) -> None:
    """Print visually structured threat intelligence card."""
    status = alert.get("status", "FLAGGED")
    risk = alert.get("risk_score", 0.0)
    tx_id = alert.get("transaction_id", "N/A")
    user_id = alert.get("user_id", "N/A")
    amount = alert.get("amount", 0.0)
    currency = alert.get("currency", "USD")

    merchant = alert.get("merchant", {})
    m_name = merchant.get("name") or alert.get("merchant_name", "Unknown")
    m_cat = merchant.get("category") or alert.get("merchant_category", "retail")

    signals = alert.get("signals", {})
    violations = signals.get("rule_violations", [])
    lgbm_p = signals.get("lgbm_fraud_prob", 0.0)
    iso_score = signals.get("anomaly_score", 0.0)

    timings = alert.get("timings", {})
    lat_ms = timings.get("inference_latency_ms", 0.0)

    print("+" + "-" * 78 + "+")
    print(
        f"| [FRAUD ALERT] Status: {status:<10} | Risk Score: {risk:<7.4f} | Latency: {lat_ms:.2f} ms"
    )
    print(f"| Transaction: {tx_id}")
    print(f"| User:        {user_id}")
    print(f"| Amount:      ${amount:,.2f} {currency} | Merchant: {m_name} ({m_cat})")
    if violations:
        print(f"| Violations:  {', '.join(violations)}")
    print(f"| AI Model:    LightGBM Prob: {lgbm_p:.4f} | Isolation Forest Score: {iso_score:.4f}")
    print("+" + "-" * 78 + "+\n")


async def run_listener(
    channel: str = settings.REDIS_ALERTS_CHANNEL,
    mock: bool = False,
    max_alerts: int | None = None,
) -> None:
    """Run real-time alerts subscriber loop."""
    print("=" * 80)
    print("Redis Pub/Sub Real-Time Fraud Alert Listener")
    print(f"Target Channel: {channel} | Mock Mode: {mock}")
    print("Waiting for high-risk threat alerts... (Press Ctrl+C to exit)")
    print("=" * 80 + "\n")

    publisher = RedisPublisher(alerts_channel=channel, mock_mode=mock)
    await publisher.initialize()

    mock_task = None
    if mock:

        async def _mock_generator() -> None:
            import random
            from uuid import uuid4

            categories = ["luxury", "electronics", "crypto", "gambling", "travel"]
            merchants = ["Rolex Vault", "CryptoSwap Instant", "Casino Royale", "FlightBooking Pro"]
            rules_sample = [
                "RULE_IMPOSSIBLE_TRAVEL",
                "RULE_VELOCITY_BURST",
                "RULE_SANCTIONED_DEST",
                "RULE_NOCTURNAL_ATO",
            ]

            while True:
                await asyncio.sleep(0.5)
                decision = {
                    "transaction_id": f"tx_{uuid4().hex[:12]}",
                    "user_id": str(uuid4()),
                    "account_id": str(uuid4()),
                    "amount": round(random.uniform(500.0, 9500.0), 2),
                    "status": random.choice(["FLAGGED", "REJECTED"]),
                    "risk_score": round(random.uniform(0.65, 0.99), 4),
                    "fraud_probability": round(random.uniform(0.70, 0.98), 4),
                    "anomaly_score": round(random.uniform(0.60, 0.95), 4),
                    "merchant_name": random.choice(merchants),
                    "merchant_category": random.choice(categories),
                    "rule_violations": random.sample(rules_sample, k=random.randint(1, 2)),
                    "latency_ms": round(random.uniform(2.5, 6.0), 2),
                }
                await publisher.publish_alert(decision)

        mock_task = asyncio.create_task(_mock_generator())

    alert_count = 0
    try:
        async for alert_payload in publisher.subscribe(channel):
            if alert_payload.get("event_type") == "FRAUD_ALERT":
                render_alert_card(alert_payload)
                alert_count += 1
                if max_alerts and alert_count >= max_alerts:
                    print(f"[*] Reached target limit of {max_alerts} alerts. Stopping.")
                    break
            elif alert_payload.get("event_type") == "SYSTEM_METRICS":
                print(f"[METRICS] Telemetry: {alert_payload}")
    except asyncio.CancelledError:
        pass
    finally:
        if mock_task is not None:
            mock_task.cancel()
            try:
                await mock_task
            except asyncio.CancelledError:
                pass
        await publisher.close()
        print(f"\n[*] Listener stopped. Total alerts received: {alert_count}")


def main() -> None:
    """CLI entrypoint for fraud alerts listener."""
    parser = argparse.ArgumentParser(description="Redis Pub/Sub Fraud Alert Listener")
    parser.add_argument(
        "--channel",
        type=str,
        default=settings.REDIS_ALERTS_CHANNEL,
        help=f"Redis pub/sub channel to listen to (default: {settings.REDIS_ALERTS_CHANNEL})",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in mock mode with synthetic incoming alerts",
    )
    parser.add_argument(
        "--max-alerts",
        type=int,
        default=None,
        help="Stop listener after receiving N alerts",
    )
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _sig():
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _sig)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        loop.run_until_complete(
            run_listener(
                channel=args.channel,
                mock=args.mock,
                max_alerts=args.max_alerts,
            )
        )
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
