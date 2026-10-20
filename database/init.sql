-- ============================================================================
-- Real-Time Fraud Detection System - Database Schema Initialization
-- Target: PostgreSQL 16 Alpine
-- ============================================================================

-- 1. Enable Cryptographic & UUID Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- 2. Schema DDL: Users, Accounts, and Transactions
-- ============================================================================

-- Customer profiles and baseline risk classification
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    phone_number VARCHAR(50),
    risk_tier VARCHAR(20) NOT NULL DEFAULT 'STANDARD'
        CHECK (risk_tier IN ('LOW', 'STANDARD', 'ELEVATED', 'HIGH')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Accounts tied to users
CREATE TABLE IF NOT EXISTS accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    account_number VARCHAR(34) NOT NULL UNIQUE,
    account_type VARCHAR(50) NOT NULL DEFAULT 'CHECKING'
        CHECK (account_type IN ('CHECKING', 'SAVINGS', 'CREDIT', 'BUSINESS')),
    balance NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'FROZEN', 'CLOSED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Immutable transaction ledger with ML feature snapshot & rule tracking
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_ref VARCHAR(64) NOT NULL UNIQUE, -- External idempotency key from Kafka
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0), -- Strict exact monetary representation
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    merchant_category VARCHAR(100) NOT NULL,
    merchant_name VARCHAR(255) NOT NULL,
    location_country VARCHAR(2) NOT NULL, -- ISO 3166-1 alpha-2
    location_lat NUMERIC(9, 6),
    location_lon NUMERIC(9, 6),
    device_id VARCHAR(128),
    ip_address INET,
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('APPROVED', 'FLAGGED', 'REJECTED')),
    risk_score NUMERIC(5, 4) NOT NULL
        CHECK (risk_score >= 0.0000 AND risk_score <= 1.0000),
    feature_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    rule_violations JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL, -- Edge transaction generation timestamp
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW() -- Inference completion timestamp
);

-- ============================================================================
-- 3. Optimized Index Architecture
-- ============================================================================

-- Primary Query Index: Composite B-Tree for User Timeline Retrieval
-- Enables instant, zero-sort Index Scans when fetching recent user transactions
CREATE INDEX IF NOT EXISTS idx_transactions_user_created
ON transactions (user_id, created_at DESC);

-- Operational Dashboard Index: Partial Index on High-Risk Decisions
-- Keeps index footprint extremely small (<2% of total rows) in RAM
CREATE INDEX IF NOT EXISTS idx_transactions_status_created
ON transactions (status, created_at DESC)
WHERE status IN ('FLAGGED', 'REJECTED');

-- Foreign Key Lookup Indexes (prevents sequential scans on FK joins)
CREATE INDEX IF NOT EXISTS idx_accounts_user
ON accounts (user_id);

CREATE INDEX IF NOT EXISTS idx_transactions_account
ON transactions (account_id);

-- Time-Series Analytical Range Index
CREATE INDEX IF NOT EXISTS idx_transactions_created_at
ON transactions (created_at DESC);

-- ============================================================================
-- 4. Initial Seed Fixtures
-- ============================================================================

-- Seed 3 standard testing profiles with fixed UUIDs for deterministic testing
INSERT INTO users (id, email, full_name, phone_number, risk_tier)
VALUES
    ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'alice.johnson@example.com', 'Alice Johnson', '+1-555-0101', 'LOW'),
    ('b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a22', 'bob.smith@example.com', 'Bob Smith', '+1-555-0102', 'STANDARD'),
    ('c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a33', 'charlie.davis@example.com', 'Charlie Davis', '+1-555-0103', 'ELEVATED')
ON CONFLICT (id) DO NOTHING;

-- Seed accounts for each user
INSERT INTO accounts (id, user_id, account_number, account_type, balance, currency, status)
VALUES
    ('a1111111-9c0b-4ef8-bb6d-6bb9bd380a11', 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'US89370400440532013000', 'CHECKING', 12500.50, 'USD', 'ACTIVE'),
    ('b2222222-9c0b-4ef8-bb6d-6bb9bd380a22', 'b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a22', 'US89370400440532013001', 'CHECKING', 3400.00, 'USD', 'ACTIVE'),
    ('c3333333-9c0b-4ef8-bb6d-6bb9bd380a33', 'c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a33', 'US89370400440532013002', 'CHECKING', 890.25, 'USD', 'ACTIVE')
ON CONFLICT (id) DO NOTHING;

-- Seed 3 representative transaction records verifying types, checks, and JSONB fields
INSERT INTO transactions (
    transaction_ref, user_id, account_id, amount, currency,
    merchant_category, merchant_name, location_country,
    location_lat, location_lon, device_id, ip_address,
    status, risk_score, feature_snapshot, rule_violations,
    created_at, processed_at
)
VALUES
    (
        'seed_tx_approved_001',
        'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
        'a1111111-9c0b-4ef8-bb6d-6bb9bd380a11',
        45.20,
        'USD',
        'grocery',
        'Whole Foods Market',
        'US',
        40.712776,
        -74.005974,
        'dev_mobile_ios_001',
        '192.0.2.1',
        'APPROVED',
        0.0450,
        '{"tx_count_1m": 1, "tx_sum_10m": 45.20, "amount_to_avg_ratio": 1.02}'::jsonb,
        '[]'::jsonb,
        NOW() - INTERVAL '10 minutes',
        NOW() - INTERVAL '10 minutes' + INTERVAL '8 milliseconds'
    ),
    (
        'seed_tx_flagged_002',
        'b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a22',
        'b2222222-9c0b-4ef8-bb6d-6bb9bd380a22',
        1850.00,
        'USD',
        'electronics',
        'Online Tech Superstore',
        'US',
        37.774929,
        -122.419418,
        'dev_web_chrome_002',
        '198.51.100.24',
        'FLAGGED',
        0.5820,
        '{"tx_count_1m": 4, "tx_sum_10m": 2400.00, "amount_to_avg_ratio": 3.85}'::jsonb,
        '["RULE_05: High amount variance relative to 10m baseline"]'::jsonb,
        NOW() - INTERVAL '5 minutes',
        NOW() - INTERVAL '5 minutes' + INTERVAL '12 milliseconds'
    ),
    (
        'seed_tx_rejected_003',
        'c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a33',
        'c3333333-9c0b-4ef8-bb6d-6bb9bd380a33',
        4999.99,
        'USD',
        'crypto',
        'Offshore Crypto Swap',
        'KY',
        19.313299,
        -81.254601,
        'dev_unknown_bot_003',
        '203.0.113.88',
        'REJECTED',
        0.9420,
        '{"tx_count_1m": 11, "tx_sum_10m": 9400.00, "amount_to_avg_ratio": 7.40}'::jsonb,
        '["RULE_01: Bot velocity burst (11 tx/60s)", "RULE_03: Nocturnal high-risk offshore destination"]'::jsonb,
        NOW() - INTERVAL '1 minute',
        NOW() - INTERVAL '1 minute' + INTERVAL '6 milliseconds'
    )
ON CONFLICT (transaction_ref) DO NOTHING;
