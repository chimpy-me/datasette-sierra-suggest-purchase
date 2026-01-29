-- Migration 0006: Login rate limit tracking

CREATE TABLE IF NOT EXISTS login_attempts (
    attempt_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    principal_type TEXT NOT NULL, -- patron or staff
    principal_id TEXT NOT NULL,   -- barcode or username
    ip TEXT,
    success INTEGER NOT NULL      -- 1 = success, 0 = failure
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_principal_ts
    ON login_attempts(principal_type, principal_id, ts);

CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_ts
    ON login_attempts(ip, ts);
