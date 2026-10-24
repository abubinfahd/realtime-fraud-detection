# Stage 08 — Redis Pub/Sub Event Fan-Out

## 1. Stage Objective & Scope

Stage 8 introduces real-time alert broadcasting from the backend inference engine to edge delivery hubs using **Redis Pub/Sub**.

In high-throughput financial architectures, the backend consumer workers must remain decoupled from edge user interfaces:
- Consumer workers must focus on Kafka ingestion, ML scoring, and database commits.
- Workers must **never** manage browser WebSocket connections or HTTP sessions directly.
- Redis Pub/Sub provides a sub-millisecond, fire-and-forget event bus enabling inference workers to broadcast high-risk alerts to horizontally scalable edge gateways without blocking the stream.

**Primary Deliverables:**
- `src/fraud_detection/storage/redis_publisher.py`: Asynchronous publisher wrapping Redis Pub/Sub with alert filtering and JSON payload formatting.
- Integration into `src/fraud_detection/streaming/consumer.py` (`scripts/run_consumer.py`) to publish alerts when transactions are `FLAGGED` or `REJECTED`.

> [!NOTE]
> **Execution Status:** **IMPLEMENTED & VERIFIED**.
> Redis Pub/Sub asynchronous event fan-out publisher (`RedisPublisher`), threat verdict filtering policy, structured `FraudAlert` schema formatting, CLI verification listener (`scripts/listen_alerts.py`), and `FraudConsumer` integration are fully implemented and verified with automated test suites.

---

## 2. Pub/Sub Fan-Out Architecture

```mermaid
flowchart LR
    subgraph Workers["Inference Consumer Workers"]
        W1["Worker Instance 1"]
        W2["Worker Instance 2"]
    end

    subgraph Filter["Verdict Filter"]
        F1{"Status?"}
    end

    subgraph Redis["Redis 7 (Pub/Sub Engine)"]
        CH["Channel: channel:fraud-alerts\n(Broadcast in < 0.2 ms)"]
    end

    subgraph Gateways["Edge Delivery Hubs"]
        GW1["FastAPI Gateway Instance A"]
        GW2["FastAPI Gateway Instance B"]
    end

    subgraph Clients["Connected Operations Dashboards"]
        C1["Security Analyst Browser"]
        C2["Fraud Operations Screen"]
    end

    W1 & W2 --> F1
    F1 -->|APPROVED (Normal)| DISCARD["Bypass Pub/Sub\n(Avoid Socket Flooding)"]
    F1 -->|FLAGGED or REJECTED| CH
    CH --> GW1 & GW2
    GW1 --> C1
    GW2 --> C2
```

---

## 3. Detailed Technical Specifications

### 3.1 Channel Topology & Traffic Filtering

Broadcasting every transaction across WebSockets under high load (e.g., 200–500 TPS) causes severe client-side browser DOM freezing and wasted egress bandwidth.

**Filtering Policy:**
- **`channel:fraud-alerts`**: Emits **only** transactions where `status IN ('FLAGGED', 'REJECTED')` or `risk_score >= 0.4000`. This isolates actionable threats, reducing message volume to ~1–5% of the total event stream.
- **`channel:system-metrics`**: Emits aggregated operational telemetry (current TPS, average inference latency, approval ratio).

---

### 3.2 High-Risk Alert Payload Schema (JSON)

Alerts contain the critical metadata required for immediate human review or automated intervention:

```json
{
  "event_type": "FRAUD_ALERT",
  "transaction_id": "tx_a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
  "user_id": "usr_99887766-5544-3322-1100-aabbccddeeff",
  "amount": 4850.00,
  "currency": "USD",
  "status": "REJECTED",
  "risk_score": 0.9420,
  "merchant": {
    "name": "Luxury Watches Direct",
    "category": "jewelry"
  },
  "signals": {
    "lgbm_fraud_prob": 0.892,
    "anomaly_score": 0.784,
    "rule_violations": ["RULE_01: Bot velocity burst (12 tx / 60s)"]
  },
  "velocity_context": {
    "tx_count_1m": 12,
    "tx_sum_10m": 5420.00
  },
  "timings": {
    "edge_timestamp": "2026-10-17T14:30:00.123456Z",
    "decision_timestamp": "2026-10-17T14:30:00.128712Z",
    "inference_latency_ms": 5.25
  }
}
```

---

### 3.3 Fire-and-Forget Semantics & Non-Blocking Guarantee

1. **Zero Downstream Coupling:** If the WebSocket gateway crashes or restarts, Redis Pub/Sub simply discards published messages on channels with zero subscribers. The Kafka consumer never hangs waiting for consumer acknowledgments.
2. **Sub-Millisecond Delivery:** Redis Pub/Sub operates entirely in memory using internal subscriber linked lists, executing in **< 0.2 ms**.

---

## 4. Implementation Deliverables

1. `src/fraud_detection/storage/redis_publisher.py`: Asynchronous Redis Pub/Sub publisher with threat filtering, schema formatting, and in-memory broker fallback.
2. `src/fraud_detection/streaming/consumer.py`: Integrated `RedisPublisher` into `FraudConsumer`, automatically routing high-risk alerts and tracking published metrics.
3. `src/fraud_detection/streaming/listener.py` & `scripts/listen_alerts.py`: CLI real-time threat alerts subscriber tool with structured card rendering.
4. `pyproject.toml`: Added `fraud-listen-alerts` CLI entrypoint script.
5. `tests/test_redis_pubsub.py`: Unit test suite verifying filtering policy, schema compliance, async subscriber reception, telemetry publishing, and consumer integration.

---

## 5. Verification & Acceptance Criteria

- [x] Connects to Redis and publishes JSON payloads asynchronously in non-blocking mode.
- [x] Strictly filters out `APPROVED` transactions from the alerts channel unless risk score is elevated.
- [x] Formats all `FLAGGED` and `REJECTED` events with complete explainability signals and velocity context.
- [x] Automated test suite `tests/test_redis_pubsub.py` passes all 6 tests.
- [x] Subscribing via `redis-cli` or `scripts/listen_alerts.py` receives live formatted alerts:
  ```bash
  # Using CLI listener
  uv run python scripts/listen_alerts.py --mock --max-alerts 5

  # Or using redis-cli with live Redis container
  docker compose exec redis redis-cli SUBSCRIBE channel:fraud-alerts
  ```
