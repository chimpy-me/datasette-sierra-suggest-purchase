# CLAUDE.md - Suggest-a-Purchase (Datasette + Sierra ILS)

## Quick Reference

```bash
# Setup
uv sync --dev && uv pip install -e .

# Run dev server
./scripts/dev.sh

# Run tests
.venv/bin/pytest tests/ -v

# Test patron: 12345678901234 / 1234
```

**Repo:** https://github.com/chimpy-me/datasette-sierra-suggest-purchase

---

## Project Status

**Current state:** POC complete and functional (28 tests passing).

**What works:**
- Patron login via Sierra (fake for dev, real API ready)
- Submit free-text purchase suggestions
- View "My Requests" with status
- Staff view/update via Datasette UI

**Immediate next steps:**
1. Add `request_events` table for audit trail
2. Add ISBN/ISSN parsing to smart bar
3. Add basic rate limiting
4. Set up CI/CD pipeline

---

## Source Documents

The `./llore/` directory contains the design inputs:

| Document | Purpose |
|----------|---------|
| `01_suggest-a-purchase-design-doc-datasette-v1.md` | Full integrated design |
| `02_suggest-a-purchase-design-doc-datasette-v2-simplified.md` | Simplified Phase 1 scope |
| `03_suggest-a-purchase-architectural-review-2day-poc.md` | 2-day POC cut plan |
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
    templates/               # Jinja2 templates for patron UI

scripts/
    dev.sh                   # One-command dev startup
    init_db.py               # Create POC schema
    fake_sierra.py           # Mock Sierra API (3 test patrons)

tests/
    unit/
        test_schema.py           # DB schema tests
        test_sierra_client.py    # Sierra client + actor tests
    integration/
        test_patron_flow.py      # Login, submit, my-requests
        test_staff_flow.py       # Status updates, auth checks

llore/                       # Design documents (read-only reference)
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
    CHECK (status IN ('new', 'in_review', 'ordered', 'declined', 'duplicate_or_already_owned'))
);
```

**Statuses:** `new` → `in_review` → `ordered` | `declined` | `duplicate_or_already_owned`

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
```

For production, update `sierra_api_base` and credentials to point to real Sierra.

---

## Datasette Hooks

| Hook | Purpose |
|------|---------|
| `register_routes()` | All patron and staff routes |
| `permission_allowed()` | Role-based access (patron vs staff) |
| `skip_csrf()` | Bypass CSRF for plugin routes (POC) |
| `prepare_jinja2_environment()` | Register templates directory |
| `extra_template_vars()` | Version info |

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

## Test Coverage (28 tests)

```bash
.venv/bin/pytest tests/ -v
```

| File | Tests |
|------|-------|
| `test_schema.py` | Schema creation, status constraints |
| `test_sierra_client.py` | Auth flow, token caching, actor building |
| `test_patron_flow.py` | Login, submit, confirmation, my-requests, logout |
| `test_staff_flow.py` | Status updates, notes, auth checks, CSV export |

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

## What's Next

### Phase 1.5 (Immediate)
1. **`request_events` table** - Audit trail (submitted, status_changed, note_added)
2. **Smart bar parsing** - ISBN-10/13, ISSN, URL detection
3. **Rate limiting** - Max N requests per patron per window
4. **CI/CD** - GitHub Actions for tests + lint

### Phase 1 MVP
- Proper CSRF tokens (replace skip_csrf hook)
- Staff queue UI (custom page with filters)
- "Already owned" hint for ISBNs

### Phase 2+
- Email verification
- Authority provider integrations
- `rule_mode=enforce` as default

---

## Open Questions (For Production)

1. **Sierra auth endpoint** - Exact endpoint/credential form for your Sierra?
2. **Eligible ptypes** - Which patron types allowed/blocked?
3. **Rate limits** - Defaults (e.g., 3 per 90 days)?
4. **Staff roles** - Which roles grant review access?
