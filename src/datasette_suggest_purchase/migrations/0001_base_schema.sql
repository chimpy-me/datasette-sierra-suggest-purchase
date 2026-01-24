-- Migration 0001: Base schema for purchase_requests
-- Original POC schema, now managed via migrations

CREATE TABLE IF NOT EXISTS purchase_requests (
    request_id TEXT PRIMARY KEY,
    created_ts TEXT NOT NULL,
    patron_record_id INTEGER NOT NULL,
    raw_query TEXT NOT NULL,
    format_preference TEXT,
    patron_notes TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    staff_notes TEXT,
    updated_ts TEXT,

    CHECK (status IN ('new', 'in_review', 'ordered', 'declined', 'duplicate_or_already_owned'))
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_requests_status_created
    ON purchase_requests(status, created_ts);

CREATE INDEX IF NOT EXISTS idx_requests_patron_created
    ON purchase_requests(patron_record_id, created_ts);
