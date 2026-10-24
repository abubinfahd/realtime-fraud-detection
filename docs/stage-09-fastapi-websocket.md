# Stage 09 — FastAPI WebSocket Hub

## 1. Stage Objective & Scope

Stage 9 builds the edge streaming gateway: an asynchronous **FastAPI WebSocket Hub**. This service acts as the bridge between internal Redis Pub/Sub channels and external browser dashboards.

**Primary Responsibilities:**
- Maintain persistent, low-overhead bidirectional WebSocket connections with client dashboards.
- Run an asynchronous background subscriber reading alerts from Redis `channel:fraud-alerts`.
- Fan out incoming alerts concurrently across all active WebSocket clients.
- Handle connection lifecycles, ping/pong heartbeats, and graceful disconnection cleanup.
- Expose REST endpoints for health checks, system metrics, and initial dashboard hydration.

**Primary Deliverables:**
- `src/fraud_detection/api/websocket_manager.py`: Thread-safe active WebSocket connection manager.
- `src/fraud_detection/api/routes/ws.py`: WebSocket endpoint handler (`/ws/live-stream`, `/ws/alerts`).
- `src/fraud_detection/api/routes/health.py`: Comprehensive readiness and component probes (`/healthz`, `/livez`, `/readyz`).
- `src/fraud_detection/api/routes/metrics.py`: Telemetry and streaming throughput metrics (`/api/v1/metrics`, `/api/v1/stats`).
- `src/fraud_detection/api/routes/alerts.py`: Recent threats for dashboard hydration (`/api/v1/alerts/recent`, `/api/v1/alerts/summary`).
- `src/fraud_detection/api/app.py`: FastAPI application entrypoint with lifespan events and modular router inclusion.
- `scripts/run_gateway.py`: Standalone CLI runner script.

> [!NOTE]
> **Execution Status:** **IMPLEMENTED & VERIFIED**.
> Sub-millisecond concurrent WebSocket fan-out, Redis Pub/Sub bridging, and dashboard hydration REST endpoints are fully operational and verified by 13 dedicated integration tests.

---

## 2. Gateway Streaming Architecture

```mermaid
flowchart TD
    subgraph PubSub["Redis Pub/Sub (Stage 8)"]
        CH["Channel: channel:fraud-alerts"]
    end

    subgraph Gateway["FastAPI Edge Gateway (Port 8000)"]
        SUB["Async Redis Subscriber Task\n(@asynccontextmanager Lifespan)"]
        MGR["WebSocket Connection Manager\n(Active Client Registry)"]
        REST["REST API:\n/healthz\n/api/v1/metrics\n/api/v1/alerts/recent"]
    end

    subgraph Browsers["Connected Client Browsers"]
        WS1["Browser Client 1 (/ws/live-stream)"]
        WS2["Browser Client 2 (/ws/live-stream)"]
        WS3["Browser Client 3 (/ws/live-stream)"]
    end

    CH -->|Async Message Stream| SUB
    SUB -->|Broadcast Payload| MGR
    MGR -->|Push JSON Frame| WS1
    MGR -->|Push JSON Frame| WS2
    MGR -->|Push JSON Frame| WS3
```

---

## 3. Detailed Technical Specifications

### 3.1 Connection Manager (`ConnectionManager`)
- Maintains a thread-safe registry `set[WebSocket]` of active client sockets.
- **Concurrent Fan-Out:** Uses `asyncio.gather` with `return_exceptions=True` to broadcast JSON frames simultaneously to all connected clients without letting a slow client block others.
- **Dead Connection Purging:** Catches `WebSocketDisconnect` and socket errors, immediately removing dead sockets from the active pool to avoid memory leaks.
- **Telemetry Counter:** Tracks total client connections, lifetime broadcast rounds, delivered frames, and service uptime.

---

### 3.2 Lifespan Background Subscriber

FastAPI utilizes an `@asynccontextmanager` lifespan handler to supervise the Redis subscriber task:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB, Redis, and launch background subscriber
    bridge_task = asyncio.create_task(_redis_pubsub_bridge(app, redis_pub))
    yield
    # Shutdown: Cancel subscriber task & drain active WebSockets
    bridge_task.cancel()
    await asyncio.wait_for(bridge_task, timeout=1.0)
    await redis_pub.close()
    await pg_pool.close()
```

---

### 3.3 Endpoints Specification

| Method | Path | Purpose |
| :--- | :--- | :--- |
| **WS** | `/ws/live-stream` | Persistent WebSocket streaming live fraud alert frames. |
| **WS** | `/ws/alerts` | Alias endpoint for live threat notifications. |
| **GET** | `/healthz` | Deep readiness probe verifying ML engine, Redis, and DB connectivity. |
| **GET** | `/livez` | Kubernetes liveness probe (`{"status": "alive"}`). |
| **GET** | `/readyz` | Kubernetes readiness probe (`200 OK` or `503 Unavailable`). |
| **GET** | `/api/v1/metrics` | Gateway telemetry: active client count, broadcast throughput, uptime. |
| **GET** | `/api/v1/alerts/recent` | Returns last 20 `FLAGGED`/`REJECTED` transactions for initial UI hydration. |
| **GET** | `/api/v1/alerts/summary` | Aggregate breakdown of processed transactions by verdict status. |
| **POST** | `/api/v1/predict` | Sub-millisecond CPU evaluation of inbound financial transaction events. |

---

## 4. Verification & Acceptance Criteria

- [x] FastAPI server starts cleanly via `uv run fraud-gateway --port 8000` or `python main.py`.
- [x] `/healthz` returns `{"status": "healthy"}` with sub-component health telemetry.
- [x] WebSocket clients can connect to `ws://localhost:8000/ws/live-stream` and receive welcome frame.
- [x] Publishing a synthetic message to Redis `channel:fraud-alerts` broadcasts the JSON frame to all active WebSocket clients within **< 2 ms**.
- [x] Disconnecting a browser client cleanly decrements the active connection counter and purges dead sockets.
- [x] Automated unit and integration tests passing in `tests/test_api.py` and `tests/test_websocket.py`.
