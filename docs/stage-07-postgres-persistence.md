# Stage 07 — PostgreSQL Persistence Layer

## 1. Stage Objective & Scope

Stage 7 implements high-throughput, asynchronous persistence of evaluated transactions into PostgreSQL 16. In streaming financial architectures, the persistence layer must balance two competing requirements:
1. **Durability & ACID Guarantees:** Financial transactions, ML feature snapshots, and fraud decisions must be stored reliably without data loss.
2. **High Write Throughput:** The database writer must ingest hundreds to thousands of records per second without introducing backpressure that stalls the Kafka consumer.

**Primary Deliverables:**
- `src/fraud_detection/storage/postgres_pool.py`: Asynchronous connection pool manager using `asyncpg`.
- `src/fraud_detection/storage/transaction_repository.py`: Repository handling micro-batched multi-row inserts and idempotency resolution.
- `src/fraud_detection/streaming/persistence_buffer.py` & `scripts/run_persistence_worker.py`: Async queue worker or embedded consumer sink that flushes scored transactions in micro-batches.

> [!NOTE]
> **Execution Status:** **IMPLEMENTED & VERIFIED**.
> High-throughput asynchronous PostgreSQL connection pooling (`asyncpg`), micro-batch repository with exact `NUMERIC(12,2)` precision, bounded dual-trigger flush buffer, and consumer integration are fully implemented and verified with automated test suites.

---

## 2. Micro-Batch Persistence Architecture

```mermaid
flowchart TD
    subgraph Consumer["Inference Consumer Worker"]
        DECISION["Scored Event:\n{tx_id, user_id, amount, status, score, features}"]
    end

    subgraph Buffer["In-Memory Async Buffer (Queue)"]
        Q["asyncio.Queue\n(Bounded Capacity: 10,000)"]
    end

    subgraph FlushCondition["Dual-Trigger Flush Logic"]
        COND{"Batch Ready?"}
        SIZE["Size Trigger: >= 50 records"]
        TIME["Timer Trigger: >= 50 ms elapsed"]
    end

    subgraph Persistence["PostgreSQL Persistence Engine"]
        POOL["asyncpg Connection Pool\n(Min: 5, Max: 20 connections)"]
        SQL["INSERT INTO transactions\n(...) VALUES ($1, $2, ...)\nON CONFLICT (transaction_ref) DO NOTHING"]
        PG[("PostgreSQL 16\n(Immutable Audit Log)")]
    end

    DECISION --> Q
    Q --> COND
    SIZE --> COND
    TIME --> COND
    COND -->|Execute Multi-Row Batch| POOL
    POOL --> SQL
    SQL --> PG
```

---

## 3. Detailed Technical Specifications

### 3.1 Why Micro-Batching Over Single-Row Inserts?

| Metric | Single-Row `INSERT` | Micro-Batched Multi-Row `INSERT` |
| :--- | :--- | :--- |
| **Network Round-Trips (RTT)** | 1 TCP round-trip per transaction | 1 TCP round-trip per 50–100 transactions |
| **Transaction Commits** | 100 fsyncs/sec to disk WAL | 1–2 fsyncs/sec to disk WAL |
| **Maximum Throughput** | ~150–250 transactions/sec | **2,500–5,000+ transactions/sec** |
| **Database CPU Usage** | High (parsing overhead per query) | Low (single statement execution plan) |

### 3.2 Dual-Trigger Flush Policy

The persistence buffer runs an asynchronous worker that flushes under two conditions:
1. **Count-based:** Flushes immediately when the in-memory queue accumulates **50 records**.
2. **Time-based:** Flushes after **50 milliseconds** even if fewer than 50 records are buffered, ensuring that under low-traffic conditions, records are persisted with imperceptible delay.

---

### 3.3 Idempotency & Conflict Resolution

During network partitions or consumer worker crashes, Kafka may redeliver already-processed messages (at-least-once delivery).
To guarantee data consistency without throwing duplicate key exceptions:

```sql
INSERT INTO transactions (
    transaction_ref, user_id, account_id, amount, currency,
    merchant_category, merchant_name, location_country,
    location_lat, location_lon, device_id, ip_address,
    status, risk_score, feature_snapshot, rule_violations,
    created_at, processed_at
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, NOW())
ON CONFLICT (transaction_ref) DO NOTHING;
```

If a duplicate `transaction_ref` arrives, PostgreSQL silently ignores the insert and returns `0` affected rows, preventing corrupting aggregate balances or double-counting transactions.

---

### 3.4 Connection Pool Optimization (`asyncpg`)

`asyncpg` communicates directly with PostgreSQL's binary frontend/backend protocol without intermediate C layers:
```python
db_pool = await asyncpg.create_pool(
    dsn="postgresql://postgres:postgres_password@localhost:5432/fraud_detection",
    min_size=5,
    max_size=20,
    max_queries=50000,
    max_inactive_connection_lifetime=300.0,
    timeout=10.0,
)
```

---

## 4. Implementation Deliverables

1. `pyproject.toml`: Added `"asyncpg>=0.29.0"` dependency.
2. `src/fraud_detection/core/config.py`: Added `POSTGRES_MIN_CONNECTIONS` (5), `POSTGRES_MAX_CONNECTIONS` (20), `POSTGRES_BATCH_SIZE` (50), `POSTGRES_FLUSH_INTERVAL_SECONDS` (0.05).
3. `src/fraud_detection/storage/postgres_pool.py`: High-performance asynchronous pool manager with offline simulator fallback.
4. `src/fraud_detection/storage/transaction_repository.py`: Multi-row batched insert repository with foreign key fixtures and indexed aggregation queries.
5. `src/fraud_detection/streaming/persistence_buffer.py` & `scripts/run_persistence_worker.py`: Async queue buffer with size/timer dual-trigger flushes and CLI test runner.
6. `src/fraud_detection/streaming/consumer.py`: Integrated persistence buffer into inference pipeline with graceful lifecycle flush.
7. `tests/test_postgres_persistence.py`: Automated unit test suite validating pool lifecycle, repository precision, idempotency, size triggers, time triggers, drain-on-stop, and consumer integration.

---

## 5. Verification & Acceptance Criteria

- [x] Connects asynchronously to PostgreSQL with connection pooling (`asyncpg`).
- [x] Successfully persists batches of scored transactions from the live consumer.
- [x] Confirms exact monetary precision (`NUMERIC(12, 2)`) without rounding anomalies (`Decimal` conversion).
- [x] Confirms point-in-time Redis velocity features are valid in `feature_snapshot JSONB`.
- [x] Re-producing duplicate events verifies `ON CONFLICT (transaction_ref) DO NOTHING` prevents duplicates.
- [x] Automated test suite `tests/test_postgres_persistence.py` passes all 7 unit tests.
- [x] Verification query executes via `psql`:
  ```bash
  docker compose exec postgres psql -U postgres -d fraud_detection -c "SELECT status, count(*), round(avg(risk_score), 4) FROM transactions GROUP BY status;"
  ```
