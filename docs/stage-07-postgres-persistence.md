# Stage 07 — PostgreSQL Persistence Layer

## 1. Stage Objective & Scope

Stage 7 implements high-throughput, asynchronous persistence of evaluated transactions into PostgreSQL 16. In streaming financial architectures, the persistence layer must balance two competing requirements:
1. **Durability & ACID Guarantees:** Financial transactions, ML feature snapshots, and fraud decisions must be stored reliably without data loss.
2. **High Write Throughput:** The database writer must ingest hundreds to thousands of records per second without introducing backpressure that stalls the Kafka consumer.

**Primary Deliverables:**
- `storage/postgres_pool.py`: Asynchronous connection pool manager using `asyncpg`.
- `storage/transaction_repository.py`: Repository handling micro-batched multi-row inserts and idempotency resolution.
- `consumers/persistence_worker.py`: Async queue worker or embedded consumer sink that flushes scored transactions in micro-batches.

> [!IMPORTANT]
> **Execution Status:** **SPECIFICATION & DESIGN PHASE**.
> Database connection pools, repositories, and persistence workers will be implemented only when explicitly triggered via `Start Step 7`.

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

## 4. Implementation Deliverables (When Triggered)

When Stage 7 is triggered (`Start Step 7`):
1. Add `asyncpg` to `pyproject.toml`.
2. Implement `storage/postgres_pool.py` providing asynchronous connection lifecycle management.
3. Implement `storage/transaction_repository.py` with multi-row batch insertion and error handling.
4. Integrate the batch buffer into `consumers/fraud_consumer.py`.
5. Update `README.md` and `docs/stage-02-database.md`.

---

## 5. Verification & Acceptance Criteria

When Stage 7 is executed, it must satisfy:
- [ ] Connects asynchronously to PostgreSQL with connection pooling.
- [ ] Successfully persists batches of scored transactions from the live consumer.
- [ ] Confirms exact monetary precision (`NUMERIC(12, 2)`) without rounding anomalies.
- [ ] Confirms point-in-time Redis velocity features are valid in `feature_snapshot JSONB`.
- [ ] Re-producing duplicate events verifies `ON CONFLICT DO NOTHING` prevents duplicates.
- [ ] Verification query executes via `psql`:
  ```bash
  docker compose exec postgres psql -U postgres -d fraud_detection -c "SELECT status, count(*), round(avg(risk_score), 4) FROM transactions GROUP BY status;"
  ```
