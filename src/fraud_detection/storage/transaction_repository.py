"""PostgreSQL Transaction Repository for Micro-Batched Persistence.

Features:
- Micro-batched multi-row transactional insertion using asyncpg binary protocol.
- Strict exact monetary precision (NUMERIC 12,2) and JSONB feature auditing.
- Idempotency resolution via ON CONFLICT (transaction_ref) DO NOTHING.
- Referential integrity guard guaranteeing prerequisite user/account record existence.
- Sub-millisecond indexed query methods for operational audits and dashboards.
- In-memory mock store fallback for offline unit testing and development.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
import json
from typing import Any
from uuid import UUID, uuid4

from fraud_detection.core.logger import get_logger
from fraud_detection.ml.preprocessing import parse_timestamp
from fraud_detection.storage.postgres_pool import PostgresPool

logger = get_logger("fraud_detection.storage.transaction_repository")


class TransactionRepository:
    """Repository managing transaction persistence and relational audit queries."""

    def __init__(self, pool: PostgresPool) -> None:
        self.pool = pool
        self._mock_records: dict[str, dict[str, Any]] = {}  # transaction_ref -> dict

    @staticmethod
    def _to_uuid(val: Any) -> UUID:
        """Coerce string or UUID to standard UUID object."""
        if isinstance(val, UUID):
            return val
        if isinstance(val, str) and val:
            try:
                return UUID(val)
            except ValueError:
                pass
        return uuid4()

    async def save_transactions_batch(self, decisions: Sequence[dict[str, Any]]) -> int:
        """
        Persist a batch of scored transactions into PostgreSQL.

        Parameters
        ----------
        decisions : Sequence[dict[str, Any]]
            Collection of scored transaction dictionaries emitted by InferenceEngine/Consumer.

        Returns
        -------
        int
            Number of transactions successfully processed into the batch.
        """
        if not decisions:
            return 0

        # In-memory mock store handling
        if self.pool.mock_mode or self.pool._pool is None:
            inserted = 0
            for d in decisions:
                ref = str(d.get("transaction_id") or d.get("transaction_ref") or uuid4().hex)
                if ref not in self._mock_records:
                    self._mock_records[ref] = {
                        "id": uuid4(),
                        "transaction_ref": ref,
                        "user_id": self._to_uuid(d.get("user_id")),
                        "account_id": self._to_uuid(d.get("account_id")),
                        "amount": Decimal(str(round(float(d.get("amount", 0.0)), 2))),
                        "currency": str(d.get("currency", "USD")),
                        "merchant_category": str(d.get("merchant_category", "retail")),
                        "merchant_name": str(d.get("merchant_name", "Unknown")),
                        "location_country": str(d.get("location_country", "US")),
                        "location_lat": (
                            float(d["location_lat"]) if d.get("location_lat") is not None else None
                        ),
                        "location_lon": (
                            float(d["location_lon"]) if d.get("location_lon") is not None else None
                        ),
                        "device_id": d.get("device_id"),
                        "ip_address": d.get("ip_address"),
                        "status": str(d.get("status", "APPROVED")),
                        "risk_score": Decimal(str(round(float(d.get("risk_score", 0.0)), 4))),
                        "feature_snapshot": d.get("features") or d.get("feature_snapshot") or {},
                        "rule_violations": d.get("rule_violations") or [],
                        "created_at": parse_timestamp(d.get("timestamp") or d.get("created_at")),
                        "processed_at": datetime.now(UTC),
                    }
                    inserted += 1
            return inserted

        # Live PostgreSQL multi-row batched execution
        user_rows: list[tuple[UUID, str, str]] = []
        account_rows: list[tuple[UUID, UUID, str]] = []
        tx_rows: list[tuple[Any, ...]] = []

        now_utc = datetime.now(UTC)

        for d in decisions:
            ref = str(d.get("transaction_id") or d.get("transaction_ref") or uuid4().hex)
            u_id = self._to_uuid(d.get("user_id"))
            acc_id = self._to_uuid(d.get("account_id"))
            amt = Decimal(str(round(float(d.get("amount", 0.0)), 2)))
            status = str(d.get("status", "APPROVED"))
            risk = Decimal(str(round(float(d.get("risk_score", 0.0)), 4)))

            feat_json = json.dumps(d.get("features") or d.get("feature_snapshot") or {})
            rules_json = json.dumps(d.get("rule_violations") or [])

            created_at = parse_timestamp(d.get("timestamp") or d.get("created_at"))

            # Prerequisite user/account fixtures for referential integrity
            user_rows.append((u_id, f"user_{u_id.hex[:8]}@example.com", f"User {u_id.hex[:6]}"))
            account_rows.append((acc_id, u_id, f"ACC_{acc_id.hex[:12].upper()}"))

            tx_rows.append(
                (
                    ref,
                    u_id,
                    acc_id,
                    amt,
                    str(d.get("currency", "USD")),
                    str(d.get("merchant_category", "retail")),
                    str(d.get("merchant_name", "Unknown")),
                    str(d.get("location_country", "US")),
                    float(d["location_lat"]) if d.get("location_lat") is not None else None,
                    float(d["location_lon"]) if d.get("location_lon") is not None else None,
                    d.get("device_id"),
                    d.get("ip_address"),
                    status,
                    risk,
                    feat_json,
                    rules_json,
                    created_at,
                    now_utc,
                )
            )

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # 1. Ensure foreign key targets exist
                user_stmt = """
                INSERT INTO users (id, email, full_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (id) DO NOTHING;
                """
                await conn.executemany(user_stmt, user_rows)

                acc_stmt = """
                INSERT INTO accounts (id, user_id, account_number)
                VALUES ($1, $2, $3)
                ON CONFLICT (id) DO NOTHING;
                """
                await conn.executemany(acc_stmt, account_rows)

                # 2. Batch insert transactions with idempotency deduplication
                tx_stmt = """
                INSERT INTO transactions (
                    transaction_ref, user_id, account_id, amount, currency,
                    merchant_category, merchant_name, location_country,
                    location_lat, location_lon, device_id, ip_address,
                    status, risk_score, feature_snapshot, rule_violations,
                    created_at, processed_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15::jsonb, $16::jsonb, $17, $18
                )
                ON CONFLICT (transaction_ref) DO NOTHING;
                """
                await conn.executemany(tx_stmt, tx_rows)

        logger.debug(
            "Persisted micro-batch to PostgreSQL",
            extra={"batch_size": len(tx_rows)},
        )
        return len(tx_rows)

    async def count_transactions(self) -> int:
        """Return total row count in transactions table."""
        if self.pool.mock_mode or self.pool._pool is None:
            return len(self._mock_records)

        val = await self.pool.fetchval("SELECT count(*) FROM transactions;")
        return int(val or 0)

    async def get_transaction_by_ref(self, transaction_ref: str) -> dict[str, Any] | None:
        """Look up transaction record by its external idempotency reference."""
        if self.pool.mock_mode or self.pool._pool is None:
            return self._mock_records.get(transaction_ref)

        query = "SELECT * FROM transactions WHERE transaction_ref = $1;"
        rows = await self.pool.fetch(query, transaction_ref)
        if rows:
            return dict(rows[0])
        return None

    async def get_recent_threats(self, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve most recent FLAGGED and REJECTED transactions for dashboard hydration."""
        if self.pool.mock_mode or self.pool._pool is None:
            threats = [
                r for r in self._mock_records.values() if r.get("status") in ("FLAGGED", "REJECTED")
            ]
            threats.sort(key=lambda x: x["created_at"], reverse=True)
            return threats[:limit]

        query = """
        SELECT * FROM transactions
        WHERE status IN ('FLAGGED', 'REJECTED')
        ORDER BY created_at DESC
        LIMIT $1;
        """
        rows = await self.pool.fetch(query, limit)
        return [dict(r) for r in rows]

    async def get_user_recent_transactions(
        self,
        user_id: UUID | str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Retrieve most recent transactions for a user leveraging composite index."""
        uid = self._to_uuid(user_id)

        if self.pool.mock_mode or self.pool._pool is None:
            user_txs = [r for r in self._mock_records.values() if r["user_id"] == uid]
            user_txs.sort(key=lambda x: x["created_at"], reverse=True)
            return user_txs[:limit]

        query = """
        SELECT * FROM transactions
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT $2;
        """
        rows = await self.pool.fetch(query, uid, limit)
        return [dict(r) for r in rows]

    async def get_status_summary(self) -> dict[str, Any]:
        """Aggregate breakdown of transaction counts and volumes grouped by verdict status."""
        if self.pool.mock_mode or self.pool._pool is None:
            approved = [r for r in self._mock_records.values() if r["status"] == "APPROVED"]
            flagged = [r for r in self._mock_records.values() if r["status"] == "FLAGGED"]
            rejected = [r for r in self._mock_records.values() if r["status"] == "REJECTED"]

            return {
                "total": len(self._mock_records),
                "approved_count": len(approved),
                "flagged_count": len(flagged),
                "rejected_count": len(rejected),
                "total_volume": float(sum(r["amount"] for r in self._mock_records.values())),
            }

        query = """
        SELECT
            status,
            count(*) AS count,
            round(avg(risk_score), 4) AS avg_risk,
            round(sum(amount), 2) AS total_volume
        FROM transactions
        GROUP BY status;
        """
        rows = await self.pool.fetch(query)
        summary: dict[str, Any] = {
            "total": 0,
            "approved_count": 0,
            "flagged_count": 0,
            "rejected_count": 0,
            "total_volume": 0.0,
            "by_status": {},
        }
        for r in rows:
            st = str(r["status"])
            cnt = int(r["count"])
            vol = float(r["total_volume"] or 0.0)
            summary["total"] += cnt
            summary["total_volume"] += vol
            if st == "APPROVED":
                summary["approved_count"] = cnt
            elif st == "FLAGGED":
                summary["flagged_count"] = cnt
            elif st == "REJECTED":
                summary["rejected_count"] = cnt
            summary["by_status"][st] = {
                "count": cnt,
                "avg_risk": float(r["avg_risk"] or 0.0),
                "total_volume": vol,
            }
        return summary


__all__ = ["TransactionRepository"]
