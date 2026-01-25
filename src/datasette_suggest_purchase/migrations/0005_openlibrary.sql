-- Migration 0005: Add Open Library enrichment support for suggest-a-bot M3
-- Applied: Milestone 3 - Open Library Enrichment

-- =============================================================================
-- Add Open Library enrichment columns to purchase_requests
-- =============================================================================

ALTER TABLE purchase_requests ADD COLUMN openlibrary_found INTEGER;
ALTER TABLE purchase_requests ADD COLUMN openlibrary_enrichment_json TEXT;
ALTER TABLE purchase_requests ADD COLUMN openlibrary_checked_ts TEXT;

-- Index for finding requests that have/haven't been enriched
CREATE INDEX IF NOT EXISTS idx_requests_openlibrary
    ON purchase_requests(openlibrary_checked_ts);

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
        'bot_evidence_extracted',
        'bot_catalog_checked',
        'bot_openlibrary_checked',  -- NEW: Open Library enrichment
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
