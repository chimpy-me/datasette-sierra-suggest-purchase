-- Migration 0002: Add request_events table and suggest-a-bot infrastructure
-- Applied: Phase 1.5 + suggest-a-bot Phase 0

-- =============================================================================
-- request_events: Audit trail for all request lifecycle changes
-- =============================================================================

CREATE TABLE IF NOT EXISTS request_events (
    event_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    actor_id TEXT NOT NULL,  -- 'patron:123', 'staff:456', 'bot:suggest-a-bot'
    event_type TEXT NOT NULL,
    payload_json TEXT,

    CHECK (event_type IN (
        -- Patron/staff events
        'submitted',
        'status_changed',
        'note_added',
        -- Bot events
        'bot_started',
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

CREATE INDEX IF NOT EXISTS idx_events_request_ts
    ON request_events(request_id, ts);

CREATE INDEX IF NOT EXISTS idx_events_type_ts
    ON request_events(event_type, ts);

-- =============================================================================
-- bot_runs: Track each suggest-a-bot processing run
-- =============================================================================

CREATE TABLE IF NOT EXISTS bot_runs (
    run_id TEXT PRIMARY KEY,
    started_ts TEXT NOT NULL,
    completed_ts TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    requests_processed INTEGER DEFAULT 0,
    requests_errored INTEGER DEFAULT 0,
    config_snapshot_json TEXT,
    error_message TEXT,

    CHECK (status IN ('running', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_bot_runs_status
    ON bot_runs(status, started_ts);

-- =============================================================================
-- Add bot-related columns to purchase_requests
-- =============================================================================

-- Bot processing status
ALTER TABLE purchase_requests ADD COLUMN bot_status TEXT DEFAULT 'pending'
    CHECK (bot_status IN ('pending', 'processing', 'completed', 'error', 'skipped'));
ALTER TABLE purchase_requests ADD COLUMN bot_processed_ts TEXT;
ALTER TABLE purchase_requests ADD COLUMN bot_error TEXT;

-- Stage 1: Catalog lookup results
ALTER TABLE purchase_requests ADD COLUMN catalog_match TEXT
    CHECK (catalog_match IN ('exact', 'partial', 'none') OR catalog_match IS NULL);
ALTER TABLE purchase_requests ADD COLUMN catalog_holdings_json TEXT;
ALTER TABLE purchase_requests ADD COLUMN catalog_checked_ts TEXT;

-- Stage 2: Consortium availability results
ALTER TABLE purchase_requests ADD COLUMN consortium_available INTEGER;
ALTER TABLE purchase_requests ADD COLUMN consortium_sources_json TEXT;
ALTER TABLE purchase_requests ADD COLUMN consortium_checked_ts TEXT;

-- Stage 3: Input refinement results
ALTER TABLE purchase_requests ADD COLUMN refined_title TEXT;
ALTER TABLE purchase_requests ADD COLUMN refined_author TEXT;
ALTER TABLE purchase_requests ADD COLUMN refined_isbn TEXT;
ALTER TABLE purchase_requests ADD COLUMN authority_source TEXT;
ALTER TABLE purchase_requests ADD COLUMN refinement_confidence REAL;

-- Stage 4: Selection guidance results
ALTER TABLE purchase_requests ADD COLUMN bot_assessment_json TEXT;
ALTER TABLE purchase_requests ADD COLUMN bot_notes TEXT;

-- Stage 5: Automatic actions
ALTER TABLE purchase_requests ADD COLUMN bot_action TEXT;
ALTER TABLE purchase_requests ADD COLUMN bot_action_ts TEXT;

-- Index for finding requests that need bot processing
CREATE INDEX IF NOT EXISTS idx_requests_bot_status
    ON purchase_requests(bot_status, created_ts);
