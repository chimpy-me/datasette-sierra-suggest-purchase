# CLAUDE.md - Suggest-a-Purchase (Datasette + Sierra ILS)

## Quick Reference

```bash
# Setup
uv sync --dev && uv pip install -e .

# Run dev server (native)
./scripts/dev.sh

# Run dev server (containers)
./scripts/container-dev.sh --build   # Build and start
./scripts/container-dev.sh           # Start (if built)
./scripts/container-dev.sh down      # Stop

# Run tests
.venv/bin/pytest tests/ -v

# suggest-a-bot CLI
.venv/bin/python -m suggest_a_bot --help
.venv/bin/python -m suggest_a_bot --db suggest_purchase.db --once
.venv/bin/python -m suggest_a_bot --db suggest_purchase.db --dry-run

# Test patron: 12345678901234 / 1234
# Staff admin: set STAFF_ADMIN_PASSWORD=yourpassword before starting
```

**Repo:** https://github.com/chimpy-me/datasette-sierra-suggest-purchase

---

## Project Status

**Current state:** POC complete + suggest-a-bot M1-M3 (321 tests passing).

**What works:**
- Patron login via Sierra (fake for dev, real API ready)
- Submit free-text purchase suggestions
- View "My Requests" with status
- Staff view/update via Datasette UI
- **suggest-a-bot infrastructure:** schema, models, config, CLI runner
- **suggest-a-bot M1:** ISBN/ISSN/DOI/URL extraction, evidence packets
- **suggest-a-bot M2:** Sierra catalog lookup with evidence-based queries
- **suggest-a-bot M3:** Open Library enrichment for items not in catalog

**Immediate next steps:**
1. Add basic rate limiting
2. Set up CI/CD pipeline
3. **suggest-a-bot M4:** Input refinement with LLM

---

## Source Documents

The `./llore/` directory contains the design inputs:

| Document | Purpose |
|----------|---------|
| `01_suggest-a-purchase-design-doc-datasette-v1.md` | Full integrated design |
| `02_suggest-a-purchase-design-doc-datasette-v2-simplified.md` | Simplified Phase 1 scope |
| `03_suggest-a-purchase-architectural-review-2day-poc.md` | 2-day POC cut plan |
| `04_suggest-a-bot-design.md` | **suggest-a-bot** automated processor design |
| `05_architecture-assessment.md` | Architecture assessment and review |
| `06_datasette-sierra-suggest-purchase_TASKS.md` | **Prioritized task list** (Datasette v1 focus) |
| `07_bot-resolution-design.md` | Bot resolution engine design |
| `08_milestone-plan.md` | Milestone plan with epics and acceptance criteria |
| `09_bot-artifacts-json-schemas.md` | JSON schemas for bot artifacts |
| `suggest_a_purchase_bootstrap_and_path.md` | Bootstrap guide + POC→MVP path |

**Key decisions from docs:**
- Datasette v1.x plugin APIs
- Signed `ds_actor` cookie for sessions
- Single SQLite database (`suggest_purchase.db`)
- Store `patron_record_id` only (no email/barcode)

---

## Project Structure

```
src/datasette_suggest_purchase/
    __init__.py              # Exports Datasette hooks
    plugin.py                # Routes, Sierra client, all hooks
    staff_auth.py            # Staff authentication (PBKDF2 hashing, env sync)
    templates/               # Jinja2 templates for patron UI
    migrations/              # SQL migrations (0001-0005)

src/suggest_a_bot/           # Background processor (M1-M3 complete)
    __init__.py              # Package init
    config.py                # YAML config loading
    models.py                # Data models + DB operations
    pipeline.py              # Processing stages (evidence, catalog, etc.)
    identifiers.py           # ISBN/ISSN/DOI/URL extraction + validation
    evidence.py              # Evidence packet builder
    catalog.py               # Sierra catalog search + CandidateSets builder
    openlibrary.py           # Open Library API client + enrichment
    run.py                   # CLI entry point

scripts/
    dev.sh                   # Native dev startup
    container-dev.sh         # Container dev startup (podman-compose)
    init_db.py               # Create schema + run migrations
    fake_sierra.py           # Mock Sierra API (3 test patrons)

containers/
    datasette/Containerfile  # Datasette + plugin image
    fake-sierra/Containerfile # Mock Sierra API image

tests/
    conftest.py                  # Shared fixtures (db_path, datasette)
    unit/
        test_schema.py           # DB schema tests
        test_sierra_client.py    # Sierra client + actor tests
        test_bot_schema.py       # Bot schema + migration tests
        test_bot_models.py       # Bot models + DB operations
        test_bot_config.py       # Bot config loading
        test_config_loading.py   # Plugin config smoke tests
        test_identifiers.py      # ISBN/ISSN/DOI/URL extraction tests
        test_evidence.py         # Evidence packet builder tests
        test_evidence_stage.py   # Evidence extraction stage tests
    integration/
        test_patron_flow.py      # Login, submit, my-requests
        test_staff_flow.py       # Status updates, auth checks

llore/                       # Design documents (read-only reference)
                             # Naming: 01_, 02_, etc. — append new docs in series
```

---

## Routes

### Patron Routes
| Method | Path | Description |
|--------|------|-------------|
| GET | `/suggest-purchase` | Login form or submission form |
| POST | `/suggest-purchase/login` | Authenticate via Sierra |
| POST | `/suggest-purchase/submit` | Create purchase request |
| GET | `/suggest-purchase/confirmation` | Show success message |
| GET | `/suggest-purchase/my-requests` | List patron's requests |
| GET | `/suggest-purchase/logout` | Clear session |

### Staff Routes
| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/suggest-purchase/staff-login` | Staff login form and auth |
| GET | `/suggest_purchase/purchase_requests` | Datasette table view |
| POST | `/-/suggest-purchase/request/<id>/update` | Update status/notes |

---

## Database Schema

```sql
CREATE TABLE purchase_requests (
    request_id TEXT PRIMARY KEY,
    created_ts TEXT NOT NULL,
    patron_record_id INTEGER NOT NULL,
    raw_query TEXT NOT NULL,
    format_preference TEXT,
    patron_notes TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    staff_notes TEXT,
    updated_ts TEXT,
    -- Bot processing fields (added in migration 0002)
    bot_status TEXT DEFAULT 'pending',
    bot_processed_ts TEXT,
    catalog_match TEXT,           -- 'exact', 'partial', 'none'
    catalog_holdings_json TEXT,
    consortium_available INTEGER,
    refined_title TEXT,
    refined_author TEXT,
    bot_assessment_json TEXT,
    bot_notes TEXT,
    -- Evidence packet (migration 0004)
    evidence_packet_json TEXT,
    evidence_extracted_ts TEXT,
    -- Open Library enrichment (migration 0005)
    openlibrary_found INTEGER,
    openlibrary_enrichment_json TEXT,
    openlibrary_checked_ts TEXT,
    CHECK (status IN ('new', 'in_review', 'ordered', 'declined', 'duplicate_or_already_owned'))
);

CREATE TABLE request_events (     -- Audit trail
    event_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    actor_id TEXT NOT NULL,       -- 'patron:123', 'staff:456', 'bot:suggest-a-bot'
    event_type TEXT NOT NULL,
    payload_json TEXT
);

CREATE TABLE bot_runs (           -- Bot execution tracking
    run_id TEXT PRIMARY KEY,
    started_ts TEXT NOT NULL,
    completed_ts TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    requests_processed INTEGER DEFAULT 0,
    requests_errored INTEGER DEFAULT 0
);

CREATE TABLE staff_accounts (     -- Staff local authentication
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,  -- PBKDF2-SHA256
    display_name TEXT,
    created_ts TEXT NOT NULL,
    updated_ts TEXT
);
```

**Statuses:** `new` → `in_review` → `ordered` | `declined` | `duplicate_or_already_owned`
**Bot statuses:** `pending` → `processing` → `completed` | `error` | `skipped`

---

## Configuration

`datasette.yaml`:
```yaml
plugins:
  datasette-suggest-purchase:
    sierra_api_base: "http://127.0.0.1:9009/iii/sierra-api"
    sierra_client_key: "fake_key"
    sierra_client_secret: "fake_secret"
    suggest_db_path: "suggest_purchase.db"
    rule_mode: "report"

    bot:
      stages:
        catalog_lookup: true
        openlibrary_enrichment: true  # Enrich from Open Library
        consortium_check: false       # Deferred until API available

      openlibrary:
        enabled: true
        timeout_seconds: 10.0
        max_search_results: 5
        run_on_no_catalog_match: true      # Enrich when not in catalog
        run_on_partial_catalog_match: true # Enrich for confidence boost
        run_on_exact_catalog_match: false  # Skip when already owned
```

For production, update `sierra_api_base` and credentials to point to real Sierra.

---

## Datasette Hooks

| Hook | Purpose |
|------|---------|
| `register_routes()` | All patron and staff routes |
| `permission_allowed()` | Custom plugin actions (submit, review, etc.) |
| `skip_csrf()` | Bypass CSRF for login routes and staff API |
| `prepare_jinja2_environment()` | Register templates directory |
| `extra_template_vars()` | Version info |
| `startup()` | Sync staff admin account from env vars |

**Note:** Table-level permissions (view-table, view-database) are handled via YAML config in `datasette.yaml` under `databases:`, not via hooks.

---

## Sierra Integration

### Auth Flow
```
1. POST /v6/token (Basic auth) → access_token
2. POST /v6/patrons/auth {barcode, pin} → patronId
3. GET /v6/patrons/{id} → ptype, home_library, names
```

### Patron Actor Shape
```json
{
  "id": "patron:100001",
  "principal_type": "patron",
  "principal_id": "100001",
  "display": "Patron Name",
  "sierra": {
    "patron_record_id": 100001,
    "ptype": 3,
    "home_library": "MAIN"
  }
}
```

---

## Test Coverage (321 tests)

```bash
.venv/bin/pytest tests/ -v
```

| File | Tests |
|------|-------|
| `test_schema.py` | Schema creation, status constraints |
| `test_sierra_client.py` | Auth flow, token caching, actor building |
| `test_sierra_catalog.py` | Catalog search methods (ISBN, title/author, items) |
| `test_patron_flow.py` | Login, submit, confirmation, my-requests, logout |
| `test_staff_flow.py` | Status updates, notes, auth checks, CSV export |
| `test_staff_login.py` | Staff login, logout, startup hook, access control |
| `test_staff_auth.py` | Password hashing, account CRUD, env sync |
| `test_permissions.py` | Table access control (anonymous, patron, staff) |
| `test_csrf.py` | CSRF token enforcement and exemptions |
| `test_bot_schema.py` | Bot schema, migrations, constraints |
| `test_bot_models.py` | BotDatabase operations, runs, events |
| `test_bot_config.py` | YAML config loading, LLM config |
| `test_config_loading.py` | Plugin config loading smoke tests |
| `test_identifiers.py` | ISBN/ISSN/DOI/URL extraction + validation |
| `test_evidence.py` | Evidence packet builder, serialization |
| `test_evidence_stage.py` | Evidence extraction stage integration |
| `test_catalog_lookup.py` | Catalog search, CandidateSets, lookup stage |
| `test_openlibrary.py` | Open Library client, data models, enrichment |
| `test_openlibrary_stage.py` | Open Library enrichment stage, pipeline integration |

---

## Commands

```bash
# Development
./scripts/dev.sh                    # Start fake Sierra + Datasette
.venv/bin/pytest tests/ -v          # Run tests

# Linting
uv run ruff check .
uv run ruff format .

# Database
uv run python scripts/init_db.py --db suggest_purchase.db
sqlite3 suggest_purchase.db "SELECT * FROM purchase_requests"

# Plugin check
uv run datasette plugins
```

---

## Current Sprint

**Focus:** suggest-a-bot Milestone 3 - Open Library Enrichment (Complete).

| Task | Status | Description |
|------|--------|-------------|
| Containers | ✅ | Add podman-compose dev environment |
| Permissions | ✅ | Move table permissions to YAML config |
| Staff auth | ✅ | Local staff accounts with PBKDF2 hashing |
| Env sync | ✅ | Auto-create admin from `STAFF_ADMIN_PASSWORD` on startup |
| **M1 Identifiers** | ✅ | ISBN/ISSN/DOI/URL extraction + validation |
| **M1 Evidence** | ✅ | Evidence packet builder + schema |
| **M1 Pipeline** | ✅ | EvidenceExtractionStage as first pipeline stage |
| **M2 Catalog Search** | ✅ | SierraClient catalog methods (ISBN, title/author, items) |
| **M2 CandidateSets** | ✅ | CandidateSets artifact builder per schema |
| **M2 CatalogLookupStage** | ✅ | Full catalog lookup stage with evidence-based search |
| **M3 Open Library Client** | ✅ | OpenLibraryClient for ISBN/title/author lookups |
| **M3 Enrichment Stage** | ✅ | OpenLibraryEnrichmentStage for metadata enrichment |
| **M3 Migration** | ✅ | Migration 0005 for openlibrary columns |
| Tests | ✅ | 321 tests covering all features |

**Full roadmap:** See `./llore/06_datasette-sierra-suggest-purchase_TASKS.md` for prioritized task list.

---

## What's Next

### suggest-a-bot Milestone 4 — Input Refinement
- Use LLM with tool-calling to normalize messy patron input
- Extract clean title/author/format from free-text requests

### P1 — Write Safety and Sierra Robustness
- **Task 4.1–4.2:** Refactor writes to Datasette async APIs, add concurrency tests
- **Task 5.1:** Expand Sierra failure-mode test coverage

### suggest-a-bot (Top-Line Feature)

**Automated background processor for purchase suggestions.** Runs periodically to enrich, validate, and triage patron requests using a local LLM with tool-calling capabilities.

See `./llore/04_suggest-a-bot-design.md` for full design.

**Processing pipeline:**
0. **Evidence extraction** ✅ - Extract ISBN/ISSN/DOI/URLs, build structured evidence packet
1. **Catalog lookup** ✅ - Check Sierra for existing holdings (duplicate detection)
2. **Open Library enrichment** ✅ - Enrich with authoritative metadata when not in catalog
3. **Consortium check** - Query OhioLINK/SearchOHIO for availability (deferred)
4. **Input refinement** - Use LLM to normalize messy patron input
5. **Selection guidance** - Generate staff-facing assessment based on collection guidelines
6. **Automatic actions** - Place holds, flag duplicates (configurable, off by default)

---

## Open Questions (For Production)

1. **Sierra auth endpoint** - Exact endpoint/credential form for your Sierra?
2. **Eligible ptypes** - Which patron types allowed/blocked?
3. **Rate limits** - Defaults (e.g., 3 per 90 days)?
4. **Staff roles** - Which roles grant review access?
