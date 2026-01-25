-- Migration 0003: Staff accounts table for local authentication
-- Passwords are stored as PBKDF2-SHA256 hashes (same as datasette-auth-passwords)

CREATE TABLE IF NOT EXISTS staff_accounts (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    created_ts TEXT NOT NULL,
    updated_ts TEXT
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_staff_accounts_username ON staff_accounts(username);
