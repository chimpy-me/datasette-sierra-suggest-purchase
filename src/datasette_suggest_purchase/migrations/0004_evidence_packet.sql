-- Migration 0004: Add evidence packet support for suggest-a-bot M1
-- Applied: Milestone 1 - Evidence-first Foundation

-- =============================================================================
-- Add evidence packet columns to purchase_requests
-- =============================================================================

ALTER TABLE purchase_requests ADD COLUMN evidence_packet_json TEXT;
ALTER TABLE purchase_requests ADD COLUMN evidence_extracted_ts TEXT;

-- Index for finding requests that have/haven't had evidence extracted
CREATE INDEX IF NOT EXISTS idx_requests_evidence
    ON purchase_requests(evidence_extracted_ts);

-- =============================================================================
-- Update request_events to support new event type
-- SQLite doesn't support ALTER CONSTRAINT, so we recreate the table
-- =============================================================================

-- Create new table with updated CHECK constraint
CREATE TABLE request_events_new (
    event_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT,

    CHECK (event_type IN (
        -- Patron/staff events
        'submitted',
        'status_changed',
        'note_added',
        -- Bot events
        'bot_started',
        'bot_evidence_extracted',  -- NEW: Evidence packet created
        'bot_catalog_checked',
        'bot_consortium_checked',
        'bot_refined',
        'bot_assessed',
        'bot_action_taken',
        'bot_completed',
        'bot_error'
    )),

    FOREIGN KEY (request_id) REFERENCES purchase_requests(request_id)
);

-- Copy existing data
INSERT INTO request_events_new
    SELECT * FROM request_events;

-- Drop old table
DROP TABLE request_events;

-- Rename new table
ALTER TABLE request_events_new RENAME TO request_events;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_events_request_ts
    ON request_events(request_id, ts);

CREATE INDEX IF NOT EXISTS idx_events_type_ts
    ON request_events(event_type, ts);
