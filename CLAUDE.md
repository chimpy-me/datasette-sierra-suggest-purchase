# CLAUDE.md - Suggest-a-Purchase (Datasette + Sierra ILS)

## Project Overview

A Datasette v1.x plugin enabling library patrons to suggest purchases, with Sierra ILS integration for authentication. Staff review suggestions through Datasette's built-in UI.

**Current state:** POC complete and functional. Ready for Phase 1 enhancements.

---

## Source Documents

The `./llore/` directory contains the design inputs (read these for full context):

| Document | Purpose |
|----------|---------|
| `01_suggest-a-purchase-design-doc-datasette-v1.md` | Full integrated design (v1 draft) |
| `02_suggest-a-purchase-design-doc-datasette-v2-simplified.md` | Simplified Phase 1 scope |
| `03_suggest-a-purchase-architectural-review-2day-poc.md` | 2-day POC cut plan + risk analysis |
| `suggest_a_purchase_bootstrap_and_path.md` | Bootstrap guide + POC→MVP path |

**Key architectural decisions from the docs:**
- Datasette v1.x plugin APIs (not 0.x compatibility)
- Signed `ds_actor` cookie for sessions
- Single SQLite database (`suggest_purchase.db`)
- Minimal PII: store `patron_record_id` only (no email/barcode)
- Auth plugin owns `actor_from_request()`; this plugin sets patron cookies

---

## What's Been Built (POC)

### Working Features

**Patron Flow:**
- `GET /suggest-purchase` → Login form (if not authenticated) or submission form
- `POST /suggest-purchase/login` → Authenticate via Sierra, set `ds_actor` cookie
- `POST /suggest-purchase/submit` → Create request in DB, redirect to confirmation
- `GET /suggest-purchase/confirmation?request_id=...` → Show success + reference
- `GET /suggest-purchase/my-requests` → List patron's own submissions with status
- `GET /suggest-purchase/logout` → Clear session

**Staff Flow:**
- View all requests via Datasette table UI: `/suggest_purchase/purchase_requests`
- CSV export via Datasette's built-in export
- `POST /-/suggest-purchase/request/<id>/update` → Update status/notes (route exists)

### Project Structure

```
src/datasette_suggest_purchase/
    __init__.py              # Exports hooks
    plugin.py                # Routes, Sierra client, Datasette hooks
    templates/
        suggest_purchase_base.html
        suggest_purchase_login.html
        suggest_purchase_form.html
        suggest_purchase_confirmation.html
        suggest_purchase_my_requests.html

scripts/
    dev.sh                   # One-command dev startup
    init_db.py               # Create POC schema
    fake_sierra.py           # Mock Sierra API (3 test patrons)

tests/
    unit/test_schema.py      # Schema tests (passing)
```

### Database Schema (POC - Single Table)

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
    CHECK (status IN ('new', 'in_review', 'ordered', 'declined', 'duplicate_or_already_owned'))
);
```

### Hooks Implemented

- `register_routes()` - All patron and staff routes
- `permission_allowed()` - Role-based access (patron vs staff)
- `skip_csrf()` - Bypass CSRF for plugin routes (POC only)
- `prepare_jinja2_environment()` - Register templates directory
- `extra_template_vars()` - Version info

---

## How to Run

```bash
# Install dependencies
uv sync --dev

# Start dev server (fake Sierra + Datasette)
./scripts/dev.sh
```

**URLs:**
- Patron UI: http://127.0.0.1:8001/suggest-purchase
- Staff view: http://127.0.0.1:8001/suggest_purchase/purchase_requests

**Test Patrons (fake Sierra):**

| Barcode        | PIN  | Name            |
|----------------|------|-----------------|
| 12345678901234 | 1234 | Test Patron One |
| 23456789012345 | 5678 | Test Patron Two |

---

## What's NOT Done Yet

### Phase 1.5 (High Impact, Next Up)

1. **`request_events` table** - Audit trail for status changes
   - Event types: `submitted`, `status_changed`, `note_added`
   - Append-only log with actor_id and timestamp

2. **Smart bar parsing** - Currently all input is free text
   - ISBN-10/13 detection + checksum validation
   - ISSN detection
   - URL classification
   - "Title by Author" splitting

3. **Basic rules engine** - Currently no enforcement
   - Rate limiting (max N per window)
   - `rule_mode=report` logs violations to `flags_json`
   - `rule_mode=enforce` blocks submission

4. **"Already owned" hint** - Check Sierra for ISBN matches

### Phase 1 MVP (Full Scope)

- Proper CSRF tokens (currently skipped via hook)
- Staff queue UI improvements (custom pages vs raw Datasette table)
- Action-based authorization (`datasette.permission_allowed()`)
- Integration tests with mocked Sierra
- CI/CD pipeline (`.github/workflows/ci.yml`)

### Phase 2+ (Deferred)

- Email verification flows
- Authority provider integrations (Wikidata, etc.)
- `rule_mode=enforce` as default
- Real Sierra integration testing

---

## Key Implementation Notes

### Sierra Authentication Flow

```python
# 1. Get OAuth token
POST /v6/token (Basic auth with client credentials)

# 2. Authenticate patron
POST /v6/patrons/auth {"barcode": "...", "pin": "..."}
→ Returns {"patronId": 123456}

# 3. Fetch patron details (optional)
GET /v6/patrons/123456
→ Returns ptype, home_library, names
```

### Actor Shape (Patron)

```json
{
  "id": "patron:100001",
  "principal_type": "patron",
  "principal_id": "100001",
  "display": "Test Patron One",
  "sierra": {
    "patron_record_id": 100001,
    "ptype": 3,
    "home_library": "MAIN"
  }
}
```

### Configuration

All config in `datasette.yaml` under `plugins.datasette-suggest-purchase`:

```yaml
sierra_api_base: "http://127.0.0.1:9009/iii/sierra-api"
sierra_client_key: "fake_key"
sierra_client_secret: "fake_secret"
suggest_db_path: "suggest_purchase.db"
rule_mode: "report"
```

---

## Test Coverage

**28 tests** covering:

### Unit Tests (`tests/unit/`)
- `test_schema.py` - POC schema creation, status constraints
- `test_sierra_client.py` - Sierra API client, token caching, actor building

### Integration Tests (`tests/integration/`)
- `test_patron_flow.py` - Login, submission, confirmation, my-requests, logout
- `test_staff_flow.py` - Status updates, notes, authorization, CSV export

Run tests with:
```bash
.venv/bin/pytest tests/ -v
```

---

## Commands Reference

```bash
# Development
./scripts/dev.sh              # Start everything
.venv/bin/pytest tests/ -v    # Run tests (use venv pytest)
uv run ruff check .           # Lint
uv run ruff format .          # Format
uv run pyright                # Type check

# Database
uv run python scripts/init_db.py --db suggest_purchase.db
sqlite3 suggest_purchase.db "SELECT * FROM purchase_requests"

# Plugin verification
uv run datasette plugins      # Should show hooks registered
```

---

## Open Questions (For Real Deployment)

1. **Sierra patron auth endpoint** - Which exact endpoint/credential form?
2. **Eligible patron types** - Which ptypes allowed/blocked?
3. **Rate limits** - What defaults (e.g., 3 per 90 days)?
4. **Staff roles** - Which RBAC roles grant review access?
5. **Email instructions** - Where do patrons update their email?

---

## File Locations

| What | Where |
|------|-------|
| Design docs | `./llore/` |
| Plugin source | `src/datasette_suggest_purchase/` |
| Templates | `src/datasette_suggest_purchase/templates/` |
| Dev scripts | `scripts/` |
| Tests | `tests/` |
| Config | `datasette.yaml` |
| Database | `suggest_purchase.db` (gitignored) |
