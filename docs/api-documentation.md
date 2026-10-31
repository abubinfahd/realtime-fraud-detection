# Real-Time Fraud Detection Streaming API — Complete API & WebSocket Documentation

This document provides the complete technical reference for all REST endpoints, HTML dashboards, observability probes, and bi-directional WebSocket protocols exposed by the **Real-Time Financial Fraud Detection Gateway** ([`src/fraud_detection/api/app.py`](../src/fraud_detection/api/app.py)).

---

## Base URLs & Interactive Explorers

| Environment | Base URL | Swagger UI (`/docs`) | ReDoc (`/redoc`) | OpenAPI JSON |
| :--- | :--- | :--- | :--- | :--- |
| **Local Development** | `http://localhost:8000` | `http://localhost:8000/docs` | `http://localhost:8000/redoc` | `http://localhost:8000/openapi.json` |
| **Azure Production VM** | `http://<VM_PUBLIC_IP>:8000` | `http://<VM_PUBLIC_IP>:8000/docs` | `http://<VM_PUBLIC_IP>:8000/redoc` | `http://<VM_PUBLIC_IP>:8000/openapi.json` |

---

## Quick Endpoint Summary

| Method | Path | Tag | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | `General` | Service identity, environment status, and navigation links |
| `POST` | `/api/v1/predict` | `Inference` | Synchronous sub-millisecond hybrid fraud scoring (LightGBM + Isolation Forest) |
| `GET` | `/api/v1/alerts/recent` | `Threat Alerts` | Fetch most recent `FLAGGED` and `REJECTED` threat alerts from PostgreSQL |
| `GET` | `/api/v1/alerts/summary` | `Threat Alerts` | Aggregate transaction counts, average risk scores, and volume by verdict |
| `GET` | `/api/v1/metrics` | `Telemetry & Metrics` | Gateway operational telemetry (active WebSockets, broadcasts, uptime, PID) |
| `GET` | `/api/v1/stats` | `Telemetry & Metrics` | Lightweight WebSocket connection manager stats for rapid polling |
| `GET` | `/healthz` | `Observability` | Deep component health check (ML Engine, Redis Pub/Sub, PostgreSQL) |
| `GET` | `/livez` | `Observability` | Lightweight container/Kubernetes liveness probe |
| `GET` | `/readyz` | `Observability` | Readiness probe verifying ML Inference Engine initialization |
| `GET` | `/dashboard/` | `UI` | Live Mission Control Real-Time Operations Dashboard (HTML/JS/WebSocket) |
| `GET` | `/mlops` | `MLOps` | Interactive MLOps Experiment Tracking & Model Registry Dashboard (HTML/Chart.js) |
| `WS` | `/ws/live-stream` | `WebSocket Streaming` | Real-time bi-directional WebSocket stream for live transactions & fraud alerts |
| `WS` | `/ws/alerts` | `WebSocket Streaming` | Alias WebSocket endpoint for real-time threat alert subscriptions |

---

## 1. Real-Time Fraud Inference (`POST /api/v1/predict`)

### Overview
Executes synchronous sub-millisecond (`< 1.5 ms`) hybrid ML scoring on a single transaction payload:
- **Supervised Model (`65%` weight)**: LightGBM gradient boosted trees (`predict_proba`).
- **Unsupervised Model (`35%` weight)**: Precomputed zero-overhead Isolation Forest C-tree depth scoring.
- **Decision Thresholds**:
  - `risk_score < 0.40` -> **`APPROVED`**
  - `0.40 <= risk_score < 0.75` -> **`FLAGGED`** (2FA / Manual Review)
  - `risk_score >= 0.75` -> **`REJECTED`** (Zero-Trust Block)

### Request Schema (`TransactionEvent`)

| Field | Type | Required | Default | Constraints & Description |
| :--- | :--- | :---: | :--- | :--- |
| `transaction_id` | `string` | Yes | — | Unique idempotency key (e.g., `"tx_demo_001"`) |
| `user_id` | `UUID` | Yes | — | Valid UUIDv4 string identifying the customer |
| `account_id` | `UUID` | Yes | — | Valid UUIDv4 string identifying the source account |
| `amount` | `float` | Yes | — | Must be `> 0.0` (monetary value in USD) |
| `currency` | `string` | No | `"USD"` | 3-character ISO 4217 currency code |
| `merchant_category` | `string` | Yes | — | Normalized to lowercase (`"grocery"`, `"retail"`, `"restaurants"`, `"utilities"`, `"entertainment"`, `"electronics"`, `"jewelry"`, `"crypto"`, `"gambling"`) |
| `merchant_name` | `string` | Yes | — | Legal merchant name |
| `location_country` | `string` | No | `"US"` | 2-character ISO 3166-1 alpha-2 country code |
| `location_city` | `string \| null` | No | `null` | City of transaction origin |
| `location_lat` | `float \| null` | No | `null` | Latitude (`-90.0` to `90.0`) |
| `location_lon` | `float \| null` | No | `null` | Longitude (`-180.0` to `180.0`) |
| `device_id` | `string \| null` | No | `null` | Client hardware/device fingerprint |
| `ip_address` | `string \| null` | No | `null` | Originating client IPv4/IPv6 address |
| `timestamp` | `ISO-8601 datetime` | No | `now(UTC)` | Event generation timestamp (e.g., `"2026-10-31T14:30:00Z"`) |
| `is_foreign_transaction` | `boolean` | No | `false` | True if cross-border / foreign country charge |
| `is_new_device` | `boolean` | No | `false` | True if unrecognized / first-seen device fingerprint |

> **Nested Object Support**: The endpoint also accepts nested `"location": {"country": "US", "city": "New York", "lat": 40.7128, "lon": -74.0060}` and `"device": {"device_id": "dev_01", "ip_address": "192.168.1.10"}` blocks automatically via Pydantic `model_validator`.

---

### Demo Body 1: Normal Everyday Transaction (`APPROVED`)

Paste this body directly into Swagger UI (`/docs` -> `POST /api/v1/predict` -> **Try it out**):

```json
{
  "transaction_id": "tx_legit_grocery_001",
  "user_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
  "account_id": "a1eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
  "amount": 42.50,
  "currency": "USD",
  "merchant_category": "grocery",
  "merchant_name": "Whole Foods Market",
  "location_country": "US",
  "location_city": "New York",
  "location_lat": 40.7128,
  "location_lon": -74.0060,
  "device_id": "dev_iphone15_alice",
  "ip_address": "192.168.1.45",
  "timestamp": "2026-10-31T14:25:00Z",
  "is_foreign_transaction": false,
  "is_new_device": false
}
```

#### Expected Response (`200 OK`)
```json
{
  "transaction_id": "tx_legit_grocery_001",
  "status": "APPROVED",
  "risk_score": 0.1142,
  "fraud_probability": 0.0008,
  "anomaly_score": 0.3249,
  "latency_ms": 0.642
}
```

---

### Demo Body 2: Suspicious Medium-Risk Foreign Electronics Purchase (`FLAGGED`)

```json
{
  "transaction_id": "tx_suspicious_electronics_002",
  "user_id": "b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a22",
  "account_id": "b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22",
  "amount": 680.00,
  "currency": "USD",
  "merchant_category": "electronics",
  "merchant_name": "Global Tech Direct",
  "location_country": "GB",
  "location_city": "London",
  "location_lat": 51.5074,
  "location_lon": -0.1278,
  "device_id": "dev_browser_session_77",
  "ip_address": "82.165.14.99",
  "timestamp": "2026-10-31T22:15:00Z",
  "is_foreign_transaction": true,
  "is_new_device": false
}
```

---

### Demo Body 3: Nocturnal Offshore Crypto Account Takeover (`REJECTED`)

```json
{
  "transaction_id": "tx_attack_crypto_ato_003",
  "user_id": "c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a33",
  "account_id": "c1eebc99-9c0b-4ef8-bb6d-6bb9bd380a33",
  "amount": 4650.00,
  "currency": "USD",
  "merchant_category": "crypto",
  "merchant_name": "Binance Global Offshore",
  "location_country": "AE",
  "location_city": "Dubai",
  "location_lat": 25.2048,
  "location_lon": 55.2708,
  "device_id": "dev_unknown_emulator_999",
  "ip_address": "185.190.44.12",
  "timestamp": "2026-10-31T03:15:00Z",
  "is_foreign_transaction": true,
  "is_new_device": true
}
```

#### Expected Response (`200 OK`)
```json
{
  "transaction_id": "tx_attack_crypto_ato_003",
  "status": "REJECTED",
  "risk_score": 0.8845,
  "fraud_probability": 0.9984,
  "anomaly_score": 0.6731,
  "latency_ms": 0.715
}
```

---

### Demo Body 4: Nested Kafka Payload Format (`location` & `device` Objects)

```json
{
  "transaction_id": "tx_nested_kafka_004",
  "user_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
  "account_id": "a1eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
  "amount": 2850.00,
  "currency": "USD",
  "merchant_category": "jewelry",
  "merchant_name": "Cartier Fifth Avenue",
  "location": {
    "country": "US",
    "city": "Miami",
    "lat": 25.7617,
    "lon": -80.1918
  },
  "device": {
    "device_id": "dev_new_unknown_404",
    "ip_address": "203.0.113.88"
  },
  "timestamp": "2026-10-31T02:45:00Z",
  "is_foreign_transaction": false,
  "is_new_device": true
}
```

---

### CLI Examples (`curl` & Windows PowerShell)

#### Using `curl` (Linux / macOS / Git Bash)
```bash
curl -X POST "http://localhost:8000/api/v1/predict" \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "tx_cli_test_01",
    "user_id": "c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a33",
    "account_id": "c1eebc99-9c0b-4ef8-bb6d-6bb9bd380a33",
    "amount": 4650.00,
    "currency": "USD",
    "merchant_category": "crypto",
    "merchant_name": "Binance Global",
    "location_country": "AE",
    "timestamp": "2026-10-31T03:15:00Z",
    "is_foreign_transaction": true,
    "is_new_device": true
  }'
```

#### Using Windows PowerShell (`Invoke-RestMethod`)
```powershell
$body = @{
  transaction_id = "tx_ps_test_01"
  user_id = "c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a33"
  account_id = "c1eebc99-9c0b-4ef8-bb6d-6bb9bd380a33"
  amount = 4650.00
  currency = "USD"
  merchant_category = "crypto"
  merchant_name = "Binance Global"
  location_country = "AE"
  timestamp = "2026-10-31T03:15:00Z"
  is_foreign_transaction = $true
  is_new_device = $true
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/predict" -Method Post -ContentType "application/json" -Body $body
```

---

## 2. Threat Alerts Endpoints

### `GET /api/v1/alerts/recent`
Retrieves the most recent `FLAGGED` and `REJECTED` transactions from PostgreSQL (ordered by `created_at DESC`) for instant dashboard hydration.

- **Query Parameters**:
  - `limit` (`integer`, optional, default: `20`, min: `1`, max: `100`): Number of recent threat alerts to return.
- **Example Request**:
  ```bash
  curl "http://localhost:8000/api/v1/alerts/recent?limit=5"
  ```
- **Example Response (`200 OK`)**:
  ```json
  [
    {
      "transaction_ref": "tx_spike_8f91a2c3d4e5",
      "user_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
      "amount": 3.45,
      "currency": "USD",
      "merchant_name": "Amazon Web Store",
      "merchant_category": "retail",
      "status": "REJECTED",
      "risk_score": 1.0,
      "rule_violations": ["RULE_01"],
      "created_at": "2026-10-31T09:15:22.418291+00:00"
    }
  ]
  ```

---

### `GET /api/v1/alerts/summary`
Returns an aggregated breakdown of all persisted transactions grouped by verdict (`APPROVED`, `FLAGGED`, `REJECTED`).

- **Example Request**:
  ```bash
  curl "http://localhost:8000/api/v1/alerts/summary"
  ```
- **Example Response (`200 OK`)**:
  ```json
  {
    "total": 12450,
    "approved_count": 11980,
    "flagged_count": 245,
    "rejected_count": 225,
    "total_volume": 1458920.50,
    "by_status": {
      "APPROVED": {
        "count": 11980,
        "avg_risk": 0.1124,
        "total_volume": 982140.25
      },
      "FLAGGED": {
        "count": 245,
        "avg_risk": 0.6412,
        "total_volume": 312450.00
      },
      "REJECTED": {
        "count": 225,
        "avg_risk": 0.9640,
        "total_volume": 164330.25
      }
    }
  }
  ```

---

## 3. Telemetry & Metrics Endpoints

### `GET /api/v1/metrics`
Returns real-time operational telemetry for the FastAPI gateway and active WebSocket fan-out hub.

- **Example Response (`200 OK`)**:
  ```json
  {
    "service": "fraud-detection-gateway",
    "active_websocket_clients": 2,
    "total_broadcasts": 4820,
    "total_frames_delivered": 9640,
    "uptime_seconds": 1425.68,
    "pid": 1,
    "timestamp": "2026-10-31T09:20:00.123456+00:00"
  }
  ```

### `GET /api/v1/stats`
Lightweight connection stats dictionary for high-frequency client polling.
```json
{
  "active_clients": 2,
  "total_connections_opened": 5,
  "total_broadcasts": 4820,
  "total_frames_delivered": 9640,
  "stale_disconnects_cleaned": 0
}
```

---

## 4. Observability & Health Probes

### `GET /healthz`
Deep component inspection across the in-memory ML Inference Engine, Redis 7 Pub/Sub broker, and PostgreSQL 16 connection pool.

```json
{
  "status": "healthy",
  "service": "fraud-detection-api",
  "version": "0.1.0",
  "environment": "production",
  "timestamp": "2026-10-31T09:21:10.004120+00:00",
  "components": {
    "ml_inference_engine": {
      "status": "up",
      "latency_ms": 0.0,
      "details": {
        "model_loaded": true,
        "bundle_path": "artifacts/fraud_model.joblib"
      }
    },
    "redis_pubsub": {
      "status": "up",
      "latency_ms": 0.012,
      "details": {
        "mock_mode": false,
        "channel": "channel:fraud-alerts"
      }
    },
    "postgres_database": {
      "status": "up",
      "latency_ms": 0.008,
      "details": {
        "mock_mode": false
      }
    }
  }
}
```

### `GET /livez` & `GET /readyz`
- **`GET /livez`**: Always returns `200 OK` (`{"status": "alive", "timestamp": "..."}`) if the ASGI event loop is responsive. Used by Docker `HEALTHCHECK`.
- **`GET /readyz`**: Returns `200 OK` (`{"status": "ready"}`) when the ML Inference Engine is loaded in memory, or `503 Service Unavailable` during cold-start initialization.

---

## 5. WebSocket Real-Time Streaming (`WS /ws/live-stream`)

### Connection URL
- `ws://localhost:8000/ws/live-stream` (or `ws://<VM_PUBLIC_IP>:8000/ws/live-stream`)
- Alias: `ws://localhost:8000/ws/alerts`

### Frame 1: Server Welcome Handshake (Sent Immediately on Connect)
```json
{
  "event_type": "CONNECTION_ESTABLISHED",
  "service": "fraud-detection-stream",
  "active_clients": 1,
  "timestamp": "2026-10-31T09:22:00.000000+00:00"
}
```

### Frame 2: Client-to-Server Commands (Heartbeats & Stats)
Clients can send either plain-text `"ping"` (returns `"pong"`) or JSON action frames:

- **Client Request**:
  ```json
  {"action": "ping"}
  ```
  **Server Response**:
  ```json
  {"event_type": "PONG", "timestamp": "2026-10-31T09:22:05.000000+00:00"}
  ```
- **Client Request**:
  ```json
  {"action": "get_stats"}
  ```
  **Server Response**:
  ```json
  {
    "active_clients": 1,
    "total_connections_opened": 1,
    "total_broadcasts": 120,
    "total_frames_delivered": 120,
    "stale_disconnects_cleaned": 0
  }
  ```

### Frame 3: Server-to-Client Broadcast Payload (`FRAUD_ALERT` / `STREAM_EVENT`)
Whenever the Kafka `FraudConsumer` scores a transaction and publishes to Redis Pub/Sub, the gateway fans out this JSON frame to all connected WebSocket clients in `< 1 ms`:

```json
{
  "event_type": "FRAUD_ALERT",
  "transaction_id": "tx_geo2_91bc44e102fa",
  "user_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
  "account_id": "a1eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
  "amount": 1420.50,
  "currency": "USD",
  "status": "REJECTED",
  "risk_score": 1.0,
  "merchant": {
    "name": "Harrods Luxury London",
    "category": "jewelry"
  },
  "merchant_name": "Harrods Luxury London",
  "merchant_category": "jewelry",
  "signals": {
    "lgbm_fraud_prob": 0.9942,
    "anomaly_score": 0.7125,
    "rule_violations": ["RULE_03"],
    "reasons": [
      "[RULE_03] Geographic impossibility: calculated speed 136842.1 km/h exceeds limit 900.0 km/h over 9578.9 km in 252.0s"
    ]
  },
  "velocity_context": {
    "tx_count_1m": 2,
    "tx_count_10m": 3,
    "tx_sum_10m": 1512.00,
    "amount_to_avg_ratio": 9.42
  },
  "inference_latency_ms": 0.812,
  "timings": {
    "edge_timestamp": "2026-10-31T09:23:10.112000+00:00",
    "decision_timestamp": "2026-10-31T09:23:10.112812+00:00",
    "inference_latency_ms": 0.812
  }
}
```
