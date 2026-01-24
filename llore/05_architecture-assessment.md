# Datasette Sierra Suggest Purchase — Architecture Assessment and Recommendations

**Scope of this document**  
This document captures a full-stack software-architecture assessment of the project as provided via ZIP. It emphasizes:

- **Design principles** (cohesion, separation of concerns, evolvability)
- **Project structure** (navigability, “where does this live?” clarity)
- **Schema and migrations** (single source of truth, upgrade safety)
- **Testing** (confidence, drift prevention, maintainable fixtures)
- **Operational readiness** (security posture, startup behavior, CI/CD)

It also reflects the project’s stated direction and phased intent, giving priority to the design trajectory described in `./llore/*` and the more current implementation intent described in `CLAUDE.md`.

---

## Executive assessment

The project is well-positioned as a proof-of-concept: it demonstrates an end-to-end patron submission flow and leverages Datasette’s native UI for staff review to keep scope under control. It includes a local fake Sierra service and meaningful tests for the patron/staff flow.

The largest architectural risks are:

1. **Low cohesion / high coupling in `plugin.py`** (it is becoming the “everything file”).
2. **Schema is defined in multiple places** (base schema + migrations + tests), and **migrations are not automatically applied** at runtime.
3. **Async handlers doing synchronous sqlite operations** (event loop blocking under concurrency).
4. **Auth/cookie model likely to conflict with staff identity** (patron uses `ds_actor` directly).
5. **Security posture is intentionally POC** (CSRF bypass, cookie hardening missing), but there is no clear migration plan from POC to Phase 1 MVP.

The good news: these issues can be corrected without major user-visible changes, and doing so will materially improve maintainability and the speed of iteration.

---

## What is strong already (keep it)

### 1) Scope discipline and product pragmatism
- Patron experience is intentionally simple and server-rendered.
- Staff workflow is intentionally minimal (Datasette UI as the review surface), which is appropriate for a POC and even an early MVP.

### 2) Developer ergonomics exist
- A “one command” local workflow (`scripts/dev.sh`) and a fake Sierra service (`scripts/fake_sierra.py`) are a strong foundation for quick iteration and demo reliability.

### 3) You are thinking in phases
- The design-history documents and `CLAUDE.md` clearly communicate what is deferred and what Phase 1.5 / MVP adds.
- “Bot” functionality exists as a separate namespace (`src/suggest_a_bot/`), which is a reasonable incubator provided the schema contract is made explicit.

---

## Key issues and recommendations

## 1) `plugin.py` is doing too much (comprehension bottleneck)

### Current risk
`src/datasette_suggest_purchase/plugin.py` currently mixes:
- Routing and request handlers
- Sierra integration client logic
- DB initialization and persistence logic
- Auth helpers and cookie decisions
- Security choices (CSRF bypass)
- Permissions policy

As features land (smart-bar parsing, request_events, rate limiting, staff queue views, bot integration), this file becomes the center of gravity—and the primary source of regressions and developer confusion.

### Recommendation: split by responsibility
Refactor into modules with explicit boundaries. Example layout:

```text
src/datasette_suggest_purchase/
  __init__.py
  plugin.py                 # hooks wiring only (register_routes, etc.)
  config.py                 # typed config parsing/validation
  auth.py                   # patron actor helpers (and future: patron cookie)
  sierra_client.py          # SierraClient + token handling
  db/
    __init__.py
    migrations.py           # runner + load SQL files
    schema/                 # 0001.sql, 0002.sql...
    repo.py                 # data access layer (CRUD + query helpers)
  web/
    routes.py               # route handlers
    templates/              # existing templates
  domain/
    models.py               # dataclasses for PurchaseRequest, etc.
  rules.py                  # rate limiting, eligibility checks
```

**Outcome:** better navigability, easier testability, reduced regression surface, and smoother phase additions.

---

## 2) Schema/migrations are not a single source of truth (and not applied automatically)

### Current risk
There are multiple schema sources:
- base schema created inline during “ensure DB exists” code path
- migrations in a separate directory
- tests embedding their own DDL strings

Additionally, migrations are run via a script, but the plugin runtime path does not automatically run migrations. This creates drift and “it works on my machine” conditions.

### Recommendation: one authoritative migration path
1. Create `db/schema/0001_initial.sql` (move initial schema out of Python strings).
2. Keep all schema evolution in `db/schema/000X_*.sql`.
3. Make **migration runner** authoritative and idempotent.
4. Ensure migrations run automatically (startup hook or lazily with a once-only guard).

#### Runtime migration strategy (pragmatic)
- **Preferred:** run migrations on Datasette startup.
- **Alternative:** run migrations on first relevant request using a process-wide lock to prevent concurrent runs.

#### Testing change
Tests should **never** embed schema DDL. Instead:
- create a temp DB
- run migrations to latest
- then exercise logic and HTTP flows

This prevents schema drift and makes upgrades safe.

---

## 3) Async handlers + synchronous sqlite calls

### Current risk
Async route handlers use `sqlite3.connect()` directly. Under concurrent load this blocks the event loop and introduces unstable latency.

### Recommendation
Prefer Datasette’s async database execution APIs. If that is not feasible immediately:
- execute sqlite work in threads via `anyio.to_thread.run_sync` as a transitional solution.

Additionally, standardize connection settings:
- consider enabling WAL mode
- configure busy timeout
- ensure consistent pragmas are applied

---

## 4) Identity/cookie model likely to conflict with staff auth

### Current risk
The plugin sets the `ds_actor` cookie for patrons. If staff and patron flows share the same host, the cookie name collision can overwrite staff identity or confuse sessions.

### Recommendation options

**Option A (best separation):** run patron UI and staff UI on different hostnames  
- Public hostname for patrons  
- Staff-only hostname for internal review  
Cookies remain distinct by domain.

**Option B (best single-host robustness):** use a separate patron cookie  
- e.g. `sp_patron_actor` for patron identity
- reserve `ds_actor` for staff auth (especially if you already have an auth plugin pattern)
- have the auth plugin mediate actor selection from both contexts

This aligns with the principle that “identity should be centralized” and reduces cross-plugin footguns.

---

## 5) Security posture is POC (plan the migration path now)

### Current state (POC-tolerable, MVP-risky)
- CSRF bypass is enabled for relevant routes
- cookies are not hardened for production deployment
- rate limiting is described but not fully enforced

### Recommendation: Phase 1 MVP security baseline
1. Remove CSRF bypass and implement CSRF tokens in templates.
2. Harden cookies:
   - `secure=True` in HTTPS deployments
   - `httponly=True`
   - intentional `samesite` (often Lax is appropriate)
   - consistent `path="/"` on set and clear
3. Implement rate limiting backed by DB and record policy decisions in `request_events` (at least “report” mode initially).

---

## Testing and CI/CD recommendations

## 1) Centralize fixtures around “migrations to latest”
Replace schema DDL strings in tests with a fixture that:
- creates a temp DB file
- runs migrations
- returns the DB path (and optionally a repository object)

Add two migration tests:
- **fresh install:** empty → latest
- **upgrade path:** version N → version N+1

## 2) Decide what to do about `suggest_a_bot` test coverage
Either:
- add unit tests for bot DB + pipeline stages, or
- make the bot optional/split it so core plugin tests remain lean

## 3) Add GitHub Actions
Minimum workflow:
- formatting and lint: `ruff format --check`, `ruff check`
- type checking: `pyright`
- tests: `pytest -q --cov` with a modest floor
- install using `uv` (consistent with your intended workflow)

---

# Action plan

## Priority 0: Unblock safe iteration (high impact, low behavior change)
- [ ] Refactor `plugin.py` into **routes / repo / sierra_client / config / auth** modules
- [ ] Make migrations **authoritative and automatic**
- [ ] Remove schema DDL from tests; tests run migrations instead

## Priority 1: Phase 1.5 alignment (per current intent)
- [ ] Implement `request_events` writes for:
  - [ ] request submitted
  - [ ] staff status changed
  - [ ] staff note updated
- [ ] Implement rate limiting (start with **report mode**)
- [ ] Add CI workflow (ruff, pyright, pytest)

## Priority 2: Phase 1 MVP hardening
- [ ] Remove CSRF bypass and add CSRF tokens to all forms
- [ ] Decide and implement identity separation strategy (Option A or B)
- [ ] Cookie hardening: secure/httponly/samesite/path consistency

## Priority 3: Keep “bot” from becoming a structural drag
- [ ] Decide: bot in-repo vs separate package
- [ ] If in-repo:
  - [ ] formalize schema ownership and migration requirements
  - [ ] add unit tests for bot pipeline

---

# Proposed refactor steps (mechanical, commit-friendly)

## Step 1: Create DB schema directory and SQL migrations
- [ ] Create `src/datasette_suggest_purchase/db/schema/`
- [ ] Move initial schema into `0001_initial.sql`
- [ ] Ensure `0002_*.sql` and later live alongside it
- [ ] Add a `schema_migrations` table if not already present

**Acceptance criteria**
- Running migrations on an empty DB yields the correct latest schema
- Running migrations twice is a no-op (idempotent)

## Step 2: Introduce a migration runner used by runtime and tests
- [ ] Implement `db/migrations.py` with a single public entrypoint:
  - `run_migrations(db_path: Path) -> None`
- [ ] Update scripts to call it
- [ ] Update runtime path to call it (startup hook or guarded lazy init)

**Acceptance criteria**
- Plugin can start from an empty directory and self-initialize schema correctly
- New columns/tables exist without running manual scripts

## Step 3: Create a repository layer
- [ ] Create `db/repo.py` with:
  - `create_request(...)`
  - `get_request(...)`
  - `list_requests_for_patron(...)`
  - `update_staff_fields(...)`
  - `insert_event(...)` (Phase 1.5)

**Acceptance criteria**
- Routes do not contain raw SQL except in exceptional cases
- Unit tests can cover repo functions without HTTP layer

## Step 4: Split web routes from plugin hooks
- [ ] Create `web/routes.py`
- [ ] Move route handlers there
- [ ] Keep `plugin.py` as thin glue that registers routes/hooks

**Acceptance criteria**
- `plugin.py` is primarily wiring and configuration

## Step 5: Fix async DB behavior
- [ ] Replace direct `sqlite3` calls with Datasette async DB execution APIs where practical
- [ ] Otherwise, isolate sqlite calls in repo and run them in threads

**Acceptance criteria**
- Handlers do not block event loop on DB operations

## Step 6: Normalize testing around migrations and repo layer
- [ ] Add `pytest` fixtures:
  - temp DB path
  - `run_migrations` call
  - repo instance
- [ ] Remove embedded schema DDL strings
- [ ] Add migration tests: fresh install + upgrade

**Acceptance criteria**
- Tests fail if migrations drift or schema is incomplete
- Coverage improves and becomes more representative

---

# Security readiness checklist (Phase 1 MVP)

## CSRF
- [ ] Remove `skip_csrf` bypass
- [ ] Add CSRF tokens to all POST forms
- [ ] Add tests for CSRF enforcement where feasible

## Cookies and session integrity
- [ ] Set cookie `secure=True` for HTTPS deployments
- [ ] Ensure `httponly=True`
- [ ] Select `samesite=Lax` or stronger where appropriate
- [ ] Set cookie `path="/"` consistently
- [ ] Make logout clear the correct cookie(s)

## Identity boundary
- [ ] Choose strategy:
  - [ ] Separate hostnames for staff/patron
  - [ ] Separate cookie name for patrons
- [ ] Ensure staff and patron sessions cannot overwrite each other

## Rate limiting
- [ ] Implement DB-backed policy tracking
- [ ] Add `request_events` logging of rate limit outcomes
- [ ] Add basic tests for rate limiting logic

---

# CI/CD checklist (minimum viable)

- [ ] Add GitHub Actions workflow for PRs:
  - [ ] install via `uv`
  - [ ] `ruff check`
  - [ ] `ruff format --check`
  - [ ] `pyright`
  - [ ] `pytest -q --cov`
- [ ] Add a modest coverage floor (start low, raise over time)
- [ ] Optionally add a “release” workflow after the above is stable

---

# Repository hygiene checklist

- [ ] Add `LICENSE` file (README references MIT; repo should include the license text)
- [ ] Ensure `README.md` reflects the real startup procedure:
  - [ ] whether migrations are automatic
  - [ ] required env vars
  - [ ] how to run fake Sierra for local dev
- [ ] Standardize config naming and documentation:
  - [ ] plugin name vs config keys
  - [ ] how to override defaults
- [ ] Consider adding `docs/architecture.md` (this file can seed it)

---

# Practical acceptance criteria (what “done” looks like)

## Structural clarity
- A new developer can locate:
  - routes, templates, db migrations, Sierra integration, auth decisions
  - without reading a single mega-file

## Schema safety
- A fresh install works with no manual init steps
- Upgrades apply reliably and are tested

## Test reliability
- No tests depend on embedded DDL strings
- Migrations are the canonical test fixture path

## Production readiness path
- CSRF bypass removed and enforced
- Cookies hardened for HTTPS deployment
- Patron/staff identity boundaries are unambiguous

---

## Appendix: Suggested “first PR” structure (minimal disruption)

- [ ] Add `db/schema/0001_initial.sql`
- [ ] Implement `db/migrations.py` runner
- [ ] Modify runtime to run migrations once
- [ ] Update tests to run migrations rather than embedded schema
- [ ] No other behavior changes

This single PR reduces the risk of schema drift and sets you up to implement Phase 1.5 features safely.

