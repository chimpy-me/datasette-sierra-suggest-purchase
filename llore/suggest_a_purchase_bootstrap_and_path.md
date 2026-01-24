# Suggest‑a‑Purchase (Datasette + Sierra) — Environment Bootstrap, Testing/CI, and POC→MVP Path

**Audience:** A developer who is new to this repo/project and needs to be productive immediately.  
**Target platform:** Datasette v1.x plugin app + SQLite + Sierra ILS REST API.  
**Primary outcome:** A credible proof‑of‑concept (POC) demo first, then a clean path to a Phase 1 MVP.

This document synthesizes and operationalizes three internal design inputs:

- `01_suggest-a-purchase-design-doc-datasette-v1.md` (integrated v1 draft)
- `02_suggest-a-purchase-design-doc-datasette-v2-simplified.md` (simplified v2 “Phase 1” plan)
- `03_suggest-a-purchase-architectural-review-2day-poc.md` (2‑day POC cut plan + architectural risks)

---

## 1. Guiding constraints (what “good” looks like)

### 1.1 Phase 1 principles (from the design docs)
We will:
- **Leverage Datasette primitives** (signed `ds_actor` cookie, action checks, server-rendered templates, SQLite as system of record).
- **Keep identity centralized**: the auth plugin is the only `actor_from_request()` provider; the suggest plugin sets `ds_actor` for patrons.
- **Minimize stored PII**: prefer Sierra `patron_record_id`; avoid email/barcode storage by default.
- **Prefer boring schema/migrations**: few tables, deterministic upgrades.

### 1.2 Two target states: POC vs Phase 1 MVP
**POC (“2‑day demo”)** = validate end‑to‑end flow with minimal complexity.  
**Phase 1 MVP** = the simplified v2 scope: “one happy path per role” with a limited smart bar + basic rules + staff queue/export.

This doc is intentionally structured to get the POC running quickly, while setting you up to graduate to Phase 1 without rewriting everything.

---

## 2. Architectural “shape” (what you are building)

### 2.1 Components
**A) Auth plugin (existing):**
- Staff login + RBAC.
- The single `actor_from_request()` implementation.
- Reads and interprets the signed Datasette `ds_actor` cookie.

**B) Suggest‑a‑Purchase plugin (this project):**
- Patron-facing pages: login, submit request, confirmation, “my requests”.
- Staff-facing pages/operations: review queue, status updates, export (POC can use Datasette table UI).
- Writes to a dedicated SQLite DB (`suggest_purchase.db`) by default.

### 2.2 Recommended deployment shape (Phase 1)
Run a **dedicated Datasette instance** for this workflow, with:
- `suggest_purchase.db` as the workflow DB
- auth plugin’s existing DB for staff RBAC (unchanged)

Rationale: keep the public-facing surface area isolated from other staff reporting instances.

---

## 3. Repository layout (recommended) and development workflow

### 3.1 Recommended repo layout (single-repo for the suggest plugin)
```
suggest-a-purchase/
  pyproject.toml
  README.md
  datasette.yaml
  src/
    datasette_suggest_purchase/
      __init__.py
      plugin.py
      templates/
      static/
      migrations/
        0001.sql
        0002.sql
  tests/
    unit/
    integration/
  scripts/
    dev.sh
    init_db.py
    fake_sierra.py
  .github/workflows/
    ci.yml
    release.yml
```

### 3.2 Local path dependency on auth plugin (for integrated dev)
You will likely develop with the auth plugin checked out next to this repo:

```
workspace/
  datasette-sierra-ils-auth/
  suggest-a-purchase/
```

In `suggest-a-purchase/pyproject.toml`, reference the auth plugin as a **local path dependency** (editable) during development.

---

## 4. Environment bootstrap with `uv`

### 4.1 Prerequisites
- Python 3.11+ recommended (match org standards; CI will run a version matrix).
- `uv` installed.
- `sqlite3` CLI installed (helpful for manual inspection).

### 4.2 One-time setup commands
From the `suggest-a-purchase/` repo root:

```bash
# 1) Create/activate the project environment and install deps
uv sync --dev

# 2) Install the auth plugin as a local editable dependency (dev workspace)
uv pip install -e ../datasette-sierra-ils-auth

# 3) Optional: install datasette itself as an explicit dependency (recommended)
uv pip install "datasette>=1.0a,<2"
```

### 4.3 Secrets/configuration
Create a `.env` (never commit) with Sierra credentials and base URL.

Example:
```bash
SIERRA_API_BASE="https://sierra-test.example.org/iii/sierra-api"
SIERRA_CLIENT_KEY="..."
SIERRA_CLIENT_SECRET="..."
```

Keep **all plugin runtime config** in `datasette.yaml` (Datasette v1 expects config here rather than legacy metadata patterns).

---

## 5. Local runtime: running Datasette for rapid iteration

### 5.1 Initialize the POC DB (minimal schema)
For the POC, start with the “Option A” single-table schema (fastest). Create `suggest_purchase.db` once:

```bash
uv run python scripts/init_db.py --db suggest_purchase.db
```

Suggested POC schema (single table):
- `purchase_requests(request_id, created_ts, patron_record_id, raw_query, format_preference, patron_notes, status, staff_notes, updated_ts)`
- Indexes: `(status, created_ts)` and `(patron_record_id, created_ts)`

### 5.2 Run Datasette locally
```bash
uv run datasette suggest_purchase.db \
  -c datasette.yaml \
  --reload \
  --host 127.0.0.1 --port 8001
```

Use `--reload` for fast iteration. If your plugin uses templates/static assets, ensure they are packaged (or in a dev-friendly path).

### 5.3 Fake Sierra for local/manual testing (strongly recommended)
To keep iteration fast and avoid environment variability, run a tiny “fake Sierra” service locally and point the app at it when developing.

```bash
uv run python scripts/fake_sierra.py --port 9009
export SIERRA_API_BASE="http://127.0.0.1:9009"
```

Your fake Sierra should implement only what the POC needs:
- Patron auth (one supported method)
- Minimal patron attribute lookup (optional for POC)

---

## 6. Testing strategy (complete, but layered)

The design documents call for both unit and integration tests, plus “boring migrations”. This section prescribes a testing stack that supports rapid iteration and high confidence.

### 6.1 Tooling
- `pytest`
- `pytest-asyncio` (if async routes/clients)
- `ruff` (lint + format)
- `pyright` (or `mypy`) for type checking
- Optional: `coverage` or `pytest-cov`

All of these run via `uv run …` to ensure consistent environments.

### 6.2 Test layers and what belongs where

#### Unit tests (fast, deterministic)
- Identifier parsing:
  - ISBN normalization + checksum validation
  - ISSN validation
  - URL classification
  - “title by author” split heuristics
- Rules evaluation (Phase 1; for POC you can defer rules beyond “must be logged in” and maybe a simple SQL rate cap).
- Actor shaping (patron actor and staff actor compatibility).

#### Integration tests (end-to-end semantics without real Sierra)
- Mock Sierra endpoints:
  - Successful patron login -> sets `ds_actor` cookie
  - Failed login -> error shown, cookie not set
- Datasette route tests:
  - `/suggest-purchase` login flow
  - `POST /suggest-purchase/submit` inserts row
  - `/suggest-purchase/my-requests` filters by `patron_record_id`
  - Staff update route changes status + notes (POC minimal)
- Security behaviors:
  - CSRF token required on POST routes
  - Cookie flags set (`HttpOnly`, `Secure`, `SameSite=Lax`)

#### Migration tests (Phase 1+)
Once you introduce a migration runner, test:
- Fresh install applies all migrations
- Upgrade from N-1 schema to N schema
- Idempotency (no double-apply)

### 6.3 Running tests locally
```bash
# fast unit tests
uv run pytest -q tests/unit

# full suite
uv run pytest

# lint/format
uv run ruff format .
uv run ruff check .

# typecheck
uv run pyright
```

---

## 7. CI/CD (modern, practical defaults)

### 7.1 CI goals
CI should prove:
- Code style + lint pass
- Types pass (or produce actionable diagnostics)
- Unit + integration tests pass
- Packaging is buildable
- Minimal security hygiene (optional: dependency audit)

### 7.2 GitHub Actions: `ci.yml` (recommended)
- Trigger: PRs + pushes to main
- Jobs:
  1. **Lint + format** (`ruff`)
  2. **Typecheck** (`pyright`)
  3. **Tests** on a Python version matrix (e.g., 3.10–3.13) using `uv`

**Key point:** run everything through `uv` for environment consistency.

Example job steps (sketch):
- `uv sync --dev`
- `uv run ruff check .`
- `uv run pyright`
- `uv run pytest`

### 7.3 Release pipeline (`release.yml`)
For a plugin, you have two realistic options:

**Option A: internal deployment only**
- Build artifacts (wheel/sdist) on tags
- Attach to GitHub Releases
- Deploy via internal tooling (pip index, container image, etc.)

**Option B: publish to PyPI**
- Tag-driven publish using trusted publishing
- Smoke test: install wheel + run minimal import test

For either approach, ensure the plugin has:
- Correct entry points / Datasette plugin registration
- Included templates/static files in the built wheel
- Versioning policy (SemVer)

---

## 8. POC implementation path (2‑day demo) with “no regret” structure

The architectural review recommends a sharply simplified POC. Implement the POC as **Phase 0**, but organize code so Phase 1 is incremental rather than a rewrite.

### 8.1 Decisions you must make before coding (avoid churn)
1. **Exact Sierra patron auth method** (endpoint + credential form).
2. Whether `ptype/home_library` is required in the POC (recommend: not required).
3. Whether rate limiting is on/off for the demo (recommend: off unless stakeholders insist).

### 8.2 POC feature list (must be in the demo)

**Patron**
- Login against Sierra (one supported method)
- Submit request (free-text + optional notes + optional format preference)
- Confirmation page
- “My requests” filtered by `patron_record_id`

**Staff**
- View all requests (Datasette table UI is acceptable)
- Update status (single minimal mechanism)

### 8.3 POC routes (minimal but real)
- `GET /suggest-purchase`  
  - If not patron-authenticated: show login form
  - Else show submission form
- `POST /suggest-purchase/login`
- `POST /suggest-purchase/submit`
- `GET /suggest-purchase/confirmation?request_id=...`
- `GET /suggest-purchase/my-requests`
- `POST /-/suggest-purchase/request/<request_id>/update` (staff only: `status`, `staff_notes`)

### 8.4 POC security minimums (public-facing)
- Signed `ds_actor` cookie with appropriate flags
- CSRF validation on POST routes
- Store minimal PII: `patron_record_id` only
- Logging (no credentials)

---

## 9. Post-POC: the clean path to Phase 1 MVP

After the demo works end-to-end, iterate in this order to converge on the simplified v2 Phase 1 scope.

### 9.1 Phase 1.5 (high impact / low risk)
1. Add `request_events` for auditability (restricted event types: `submitted`, `status_changed`, `note_added`).
2. Add “already owned” hint for ISBN (staff-visible flag, not a blocker).
3. Introduce `rule_mode=report` with a small initial ruleset once staff agrees on thresholds.
4. Upgrade “smart bar” incrementally:
   - ISBN normalization
   - ISSN
   - URL classification
   - Title/author split heuristics

### 9.2 Phase 1 MVP (v2 simplified target)
Add/confirm:
- Deterministic smart-bar parsing (ISBN/ISSN/URL/text) with strict raw input preservation.
- Minimal action set:
  - `suggest_purchase_submit`
  - `suggest_purchase_view_own`
  - `suggest_purchase_review`
  - `suggest_purchase_update`
  - `suggest_purchase_export`
- Status set kept small: `new`, `in_review`, `ordered`, `declined`, `duplicate_or_already_owned`.
- Dedicated instance deployment supported as the default.
- Optional patron cache only if required (rate limiting or analytics), defaulting to no email storage.

### 9.3 Phase 2+ (deferred “framework” work)
- `mode=enforce` default after staff sign-off on thresholds.
- Authority providers interface + candidate selection UI (Wikidata or others).
- Email verification flows only if truly required.

---

## 10. Definition of Done: POC and Phase 1

### 10.1 POC is “done” when
- Patron login works against Sierra (or fake Sierra for demo) and results in a patron actor cookie.
- Patron can submit request; request is persisted; confirmation shown.
- Patron can view “my requests” and see staff updates.
- Staff can view all requests in Datasette and update status via one route.
- Basic security minimums are in place (CSRF + cookie flags).

### 10.2 Phase 1 is “done” when
- Smart bar parsing + report-mode rules exist with good test coverage.
- Staff review flow exists (queue/detail pages or explicitly documented reliance on Datasette UI).
- Audit log exists (`request_events`) and is user-visible to staff.
- CI is green with matrix tests, lint, type checks.
- A developer can run locally from scratch in <15 minutes using this doc.

---

## Appendix A: Suggested `pyproject.toml` essentials (sketch)

```toml
[project]
name = "datasette-suggest-purchase"
version = "0.0.1"
requires-python = ">=3.11"
dependencies = [
  "datasette>=1.0a,<2",
  "sierra-ils-utils>=0.0.0",  # pin appropriately
]

[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-asyncio",
  "ruff",
  "pyright",
  "pytest-cov",
]

[tool.ruff]
line-length = 100

[tool.pyright]
typeCheckingMode = "standard"
```

---

## Appendix B: Suggested `datasette.yaml` (minimal sketch)

```yaml
plugins:
  datasette_suggest_purchase:
    suggest_db_path: "suggest_purchase.db"
    rule_mode: "report"
    rules:
      rate_limit:
        max: 3
        window_days: 90
  datasette_sierra_ils_auth:
    # auth plugin config here (RBAC DB path, etc.)

settings:
  default_page_size: 50
```

---

## Appendix C: Dev scripts (recommended)

- `scripts/init_db.py`: creates the POC schema quickly.
- `scripts/fake_sierra.py`: tiny local service for manual testing.
- `scripts/dev.sh`: one-command run: init DB + run datasette + print URLs.

---

## Appendix D: Quick troubleshooting checklist

- If patron login “works” but actor is missing:
  - Verify `datasette.set_actor_cookie()` is called on successful login.
  - Verify cookie is not being overwritten by staff login (keep login paths distinct).
- If POST routes fail:
  - Confirm CSRF token validation is implemented and tests cover it.
- If staff can see patron-only routes:
  - Confirm `datasette.allowed(action=...)` checks are used consistently.

