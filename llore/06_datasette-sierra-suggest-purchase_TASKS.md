# Datasette Sierra Suggest Purchase — Focused Task List (Datasette v1)

This document is a focused, repo-executable task list distilled from the recent discussion, prioritized for **Datasette v1** correctness and for strong CI/test signal quality.

---

## P0 — Stabilize CI and align with Datasette v1 configuration model

### Task 0.1 — Commit a reproducible dependency lock and freeze CI installs

**Why:** Datasette v1 (especially alphas) plus unpinned transitive dependencies can create nondeterministic CI failures.

**Work:**

- Generate and commit `uv.lock`.
- Update all GitHub Actions jobs to use `uv sync --extra dev --frozen`.
- Ensure jobs explicitly set Python via `actions/setup-python` (use the same versions you test).

**Acceptance criteria:**

- CI uses the lockfile and fails if lockfile is out-of-date.
- Re-running CI for the same commit yields identical dependency resolution.

---

### Task 0.2 — Align Python version expectations across repo tooling

**Why:** Reduce “pyright vs runtime” inconsistencies and drift.

**Work:**

- Decide whether the project standard is Python **3.11** or **3.12** (recommend 3.12 unless we must support 3.11).
- Align:
  - `.python-version`
  - `pyproject.toml` (`pyright.pythonVersion`)
  - CI job defaults (lint/typecheck/test)

**Acceptance criteria:**

- A single Python “project standard” is documented and used in CI + local dev.
- `pyright` runs under that standard and produces consistent results.

---

## P0 — Update tests and app wiring for Datasette v1: `config=` not `metadata=`

### Task 1.1 — Migrate test harnesses from `metadata={...}` to `config={...}`

**Why:** Datasette v1 splits *metadata* from *configuration*; tests should reflect canonical v1 behavior.

**Work:**

- Replace usages of `Datasette(..., metadata=...)` for plugin config with `Datasette(..., config=...)`.
- Keep metadata only for actual metadata (titles, descriptions, licenses), not plugin settings.

**Acceptance criteria:**

- All tests pass using `config=` for plugin configuration.
- No plugin behavior depends on v0.x-era configuration semantics.

---

### Task 1.2 — Add a config-loading smoke test

**Why:** Prevent mis-keyed plugin config that passes tests but fails in a real Datasette config file.

**Work:**

- Add an integration test that instantiates Datasette with a `config` dict containing the plugin config under the expected plugin key.
- Assert the plugin reads the expected values via `datasette.plugin_config(...)`.

**Acceptance criteria:**

- Test fails if the plugin config key/name is wrong or the config isn’t applied.

---

## P0 — Permissions model: make it correct for Datasette v1 and prove it in tests

### Task 2.1 — Decide minimum supported Datasette v1 baseline and enforce it

**Why:** Permissions APIs changed; you need a firm version policy.

**Work:**

- Target current v1 APIs (v1 stable or recent alpha) and migrate off legacy permission hooks.

**Acceptance criteria:**

- `pyproject.toml` declares a coherent Datasette version constraint.
- CI runs against that version policy.

---

### Task 2.2 — Implement Datasette v1 permissioning using current APIs

**Why:** Legacy `permission_allowed()` can break or behave differently across v1 releases; access control is a core risk surface.

**Work:**

- Replace or complement legacy permission logic with Datasette v1 approaches:
  - action registration (`register_actions`)
  - permission resources (`permission_resources_sql()` where applicable)
  - use `datasette.allowed()` where needed
- Define explicit permissions for:
  - staff-only update endpoints
  - staff-only exports (JSON/CSV/table) if required
  - patron-only “my requests”
  - public vs authenticated access to submission flow

**Acceptance criteria:**

- Permissions are enforceable and centralized (no accidental bypass endpoints).
- Works on the chosen Datasette v1 baseline.

---

### Task 2.3 — Add security/data-exposure integration tests

**Why:** Prevent accidental exposure via Datasette’s default table endpoints and exports.

**Work:** Add integration tests that assert:

- Unauthenticated users cannot access staff endpoints or raw table exports.
- Patrons cannot access staff endpoints or full-dataset exports.
- Staff can access necessary exports and update actions.
- Patron “my requests” shows only their own requests.

**Acceptance criteria:**

- Tests cover: HTML table page, row pages, `.json`, `.csv` endpoints as applicable.
- Failing permission enforcement returns expected status codes (401/403) and does not leak data.

---

## P0 — CSRF correctness: remove the skip and test it

### Task 3.1 — Remove blanket CSRF skip for state-changing routes

**Why:** Disabling CSRF is not a viable v1 posture once you have authenticated actors and write endpoints.

**Work:**

- Remove/limit `skip_csrf()` so write endpoints require CSRF tokens.
- Update templates/forms to include CSRF token in POSTs.
- Ensure API-style POSTs (if any) follow a deliberate, documented pattern.

**Acceptance criteria:**

- POST without CSRF token fails.
- POST with a valid CSRF token succeeds.

---

### Task 3.2 — Add CSRF integration tests for every write path

**Work:**

- Patron submission POST: requires CSRF.
- Staff update status/notes POST: requires CSRF.
- Any bot-trigger endpoints invoked from a browser session: require CSRF.

**Acceptance criteria:**

- Each write endpoint has a “fails without token / passes with token” test.

---

## P1 — Replace direct sqlite3 writes with Datasette write APIs and validate under concurrency

### Task 4.1 — Refactor writes to use Datasette async write helpers

**Why:** Sync sqlite3 connections inside async handlers will eventually cause locking and responsiveness issues.

**Work:**

- Replace direct `sqlite3.connect(...)` writes with:
  - `db.execute_write(...)`, `execute_write_fn(...)`, or `execute_write_script(...)` as appropriate.
- Configure WAL mode / pragmas as needed for concurrency (if you control DB initialization).

**Acceptance criteria:**

- All write paths use Datasette DB write APIs.
- No direct sqlite3 connections in request handlers (unless justified and documented).

---

### Task 4.2 — Add a concurrency test for patron submissions

**Work:**

- Spawn N concurrent submissions using `asyncio.gather`.
- Verify all rows insert successfully with no “database is locked” errors.

**Acceptance criteria:**

- Test reliably passes in CI.
- If a regression reintroduces locking, the test fails deterministically.

---

## P1 — Sierra integration contract tests (still offline/deterministic)

### Task 5.1 — Expand mocked Sierra tests to cover failure modes

**Work:** Add test cases for:

- timeout
- 401/403
- 500
- malformed JSON
- connection error

Validate user-facing behavior:

- error messaging is clear
- no partial auth session is left behind
- no request rows inserted on auth failure

**Acceptance criteria:**

- Each failure mode has a test and an expected response contract.

---

### Task 5.2 — Optional: contract test against `scripts/fake_sierra.py`

**Work:**

- Run the fake server in tests (random port).
- Hit real `SierraClient` code without mocks for a small, stable suite.

**Acceptance criteria:**

- Confirms request/response shapes and error translation without real Sierra credentials.

---

## P2 — CI enhancements for long-term maintainability

### Task 6.1 — Add coverage reporting and threshold gating

**Work:**

- Enable `pytest-cov` in CI output.
- Add a modest initial threshold and ratchet over time.

**Acceptance criteria:**

- CI shows a coverage summary.
- Coverage threshold prevents accidental major regressions.

---

### Task 6.2 — Add a packaging smoke test job

**Work:**

- Build sdist/wheel in CI.
- Install the wheel into a clean environment.
- Import the plugin and run a minimal Datasette startup check.

**Acceptance criteria:**

- A broken wheel fails CI even if editable installs pass.

---

### Task 6.3 — Datasette v1 compatibility matrix

**Work:**

- Add a CI matrix dimension for Datasette versions:
  - minimum supported
  - “latest v1” (or a deliberately pinned latest)
- Run the integration tests against both.

**Acceptance criteria:**

- CI fails if a new Datasette v1 breaks the project, providing early warning.

---

## Suggested execution order (fastest path to a safe demo)

1. Task 0.1, 1.1, 1.2 (stability + correct v1 config)
2. Task 2.1–2.3 (permissions + data exposure protections)
3. Task 3.1–3.2 (CSRF correctness)
4. Task 4.1–4.2 (write safety + concurrency)
5. Task 5.1 (Sierra failure-mode coverage)
6. Task 6.* (coverage, packaging, version matrix)
