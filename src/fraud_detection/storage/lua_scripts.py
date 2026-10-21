"""Pre-compiled Redis Lua scripts for atomic sliding-window operations.

Executes eviction, ingestion, dual sliding-window aggregation, and TTL
extension in a single round-trip (RTT) to guarantee sub-millisecond execution.
"""

# Lua script to ingest a transaction and atomically compute 1m and 10m metrics
SLIDING_WINDOW_INGEST_SCRIPT = """
-- KEYS[1]: user:{user_id}:tx_history
-- ARGV[1]: current_timestamp_ms
-- ARGV[2]: member_string (tx_id:amount)
-- ARGV[3]: window_60s_cutoff_ms
-- ARGV[4]: window_600s_cutoff_ms
-- ARGV[5]: ttl_seconds (default 1800)

-- 1. Evict entries strictly older than 10 minutes
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', '(' .. ARGV[4])

-- 2. Add current transaction
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[2])

-- 3. Fetch items in 60s and 10m windows
local items_60s = redis.call('ZRANGEBYSCORE', KEYS[1], ARGV[3], '+inf')
local items_10m = redis.call('ZRANGEBYSCORE', KEYS[1], ARGV[4], '+inf')

-- 4. Aggregate 60s window metrics
local count_60s = #items_60s
local sum_60s = 0.0
for i = 1, count_60s do
    local m = items_60s[i]
    local idx = string.find(m, ":")
    if idx then
        local amt = tonumber(string.sub(m, idx + 1))
        if amt then
            sum_60s = sum_60s + amt
        end
    end
end

-- 5. Aggregate 10m window metrics
local count_10m = #items_10m
local sum_10m = 0.0
for i = 1, count_10m do
    local m = items_10m[i]
    local idx = string.find(m, ":")
    if idx then
        local amt = tonumber(string.sub(m, idx + 1))
        if amt then
            sum_10m = sum_10m + amt
        end
    end
end

-- 6. Refresh sliding TTL (30 minutes)
redis.call('EXPIRE', KEYS[1], ARGV[5])

return {count_60s, tostring(sum_60s), count_10m, tostring(sum_10m)}
"""

# Lua script to query existing velocity metrics without writing a new transaction
GET_VELOCITY_READ_SCRIPT = """
-- KEYS[1]: user:{user_id}:tx_history
-- ARGV[1]: window_60s_cutoff_ms
-- ARGV[2]: window_600s_cutoff_ms

-- 1. Evict entries strictly older than 10 minutes
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', '(' .. ARGV[2])

-- 2. Fetch items
local items_60s = redis.call('ZRANGEBYSCORE', KEYS[1], ARGV[1], '+inf')
local items_10m = redis.call('ZRANGEBYSCORE', KEYS[1], ARGV[2], '+inf')

local count_60s = #items_60s
local sum_60s = 0.0
for i = 1, count_60s do
    local m = items_60s[i]
    local idx = string.find(m, ":")
    if idx then
        local amt = tonumber(string.sub(m, idx + 1))
        if amt then
            sum_60s = sum_60s + amt
        end
    end
end

local count_10m = #items_10m
local sum_10m = 0.0
for i = 1, count_10m do
    local m = items_10m[i]
    local idx = string.find(m, ":")
    if idx then
        local amt = tonumber(string.sub(m, idx + 1))
        if amt then
            sum_10m = sum_10m + amt
        end
    end
end

return {count_60s, tostring(sum_60s), count_10m, tostring(sum_10m)}
"""

__all__ = [
    "GET_VELOCITY_READ_SCRIPT",
    "SLIDING_WINDOW_INGEST_SCRIPT",
]
