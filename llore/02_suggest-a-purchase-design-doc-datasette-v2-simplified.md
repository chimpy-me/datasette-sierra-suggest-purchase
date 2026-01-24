# Design Document v2: Suggest a Purchase (Datasette v1 + Sierra ILS)
**Status:** Draft (refined for simplicity)  
**Last updated:** 2026-01-24  
**Primary users:** Library patrons (public)  
**Secondary users:** Staff reviewers / selectors  
**Platform:** Datasette v1.x (ASGI), SQLite, Sierra ILS (REST API)

This document is a scoped, simplified refinement of the prior v1 draft. It keeps the same core outcomes—patron submission + staff review—but reduces moving parts, avoids premature abstractions, and tightens Phase 1 scope.

---

## 1. Design principles (non-negotiable)

1. **One “happy path” per role in Phase 1**
   - Patron: login → submit → see confirmation → view own submissions
   - Staff: login → queue → open → decide → record decision → export

2. **Leverage Datasette primitives before inventing new ones**
   - Signed `ds_actor` cookie
   - Action-based authorization (`datasette.allowed(...)`)
   - Server-side templates + simple HTML forms
   - SQLite as the system of record

3. **Minimize long-term coupling**
   - Avoid a “shared core library” in Phase 1 unless/until duplication is proven.
   - Keep the “auth plugin” as the *only* `actor_from_request()` provider.

4. **Minimize PII stored locally**
   - Store the minimum needed to:
     - enforce eligibility/rate limits
     - let staff locate the patron in Sierra
     - support basic auditing
   - Prefer **Sierra patron record id** over email/barcode storage.

5. **Migrations must be boring**
   - Small number of tables.
   - A tiny, deterministic migration runner inside the plugin (schema version + numbered SQL).

---

## 2. Phase 1 scope (what we will actually ship)

### 2.1 In scope (Phase 1)
- Patron authentication against Sierra (barcode + PIN, or whatever your Sierra configuration uses), resulting in a **patron actor** stored in the signed `ds_actor` cookie.
- A single “smart bar” input that accepts:
  - ISBN-10/13
  - ISSN
  - free text (“Title by Author”)
  - (optional) URL (stored as-is)
- A submission record persisted to SQLite.
- Staff queue + detail page:
  - view all requests
  - change status
  - add internal notes
  - export CSV

### 2.2 Explicitly out of scope (Phase 1)
- Email verification flows
- Automated ordering / acquisitions integration
- Authority provider integrations (Wikidata, etc.)
- “Already owned” checks (optional Phase 1.5; see roadmap)
- Multi-database “choose one DB vs two DBs” complexity beyond a single supported default

---

## 3. Architecture (simple + maintainable)

### 3.1 Plugins and responsibility boundaries

**Auth plugin (existing)**
- Provides **the only** `actor_from_request()` implementation.
- Continues staff login + RBAC.
- Reads `ds_actor` cookie and returns the actor dict.

**Suggest-a-purchase plugin (this project)**
- Provides public patron pages and staff review pages.
- Implements patron login route(s) that **set** the `ds_actor` cookie to a patron actor using `datasette.set_actor_cookie()`.
- Defines the Datasette **actions** used to guard staff-only routes and patron submission routes.

This keeps “who is the user?” centralized (auth plugin), while keeping “what can they do?” in action checks on every write route.

### 3.2 Deployment shape (Phase 1: one supported default)

Run a **dedicated** Datasette instance for this workflow.

- **SQLite DB file:** `suggest_purchase.db`
- **Tables inside:** purchase requests + event log (+ optional small patron cache, see below)
- **Auth DB:** whatever the auth plugin already uses for staff RBAC (unchanged)

This avoids mixing this public-facing workflow into broader staff reporting instances and keeps the security boundary clear.

---

## 4. Actor model (stable contract, minimal fields)

We keep a stable actor contract, but Phase 1 only needs a subset.

### 4.1 Patron actor (Phase 1)

```json
{
  "id": "patron:{patron_record_id}",
  "principal_type": "patron",
  "principal_id": "{patron_record_id}",
  "display": "Patron",
  "sierra": {
    "patron_record_id": 123456,
    "ptype": 3,
    "home_library": "MAIN"
  }
}
```

Notes:
- We do **not** store patron email in the actor by default. Staff can look up contact details in Sierra using the record id.
- If the library later decides staff need the email surfaced, add it as an explicit Phase 2 decision.

### 4.2 Staff actor (unchanged)

Continue using the existing staff actor schema from the auth plugin.

---

## 5. Authorization model (small set of actions)

Define a minimal set of actions and use them everywhere (routes and writes):

- `suggest_purchase_submit`
  - Patron can submit if authenticated **and** passes eligibility rules.
- `suggest_purchase_view_own`
  - Patron can view only their own requests.
- `suggest_purchase_review`
  - Staff can view queue + details.
- `suggest_purchase_update`
  - Staff can change status and add notes.
- `suggest_purchase_export`
  - Staff can export CSV.

Staff role mapping happens in the existing RBAC tables (auth DB). The suggest plugin should not embed role names in code.

---

## 6. Patron UX (Phase 1)

### 6.1 Patron pages
- `GET  /suggest-purchase`  
  - If not authenticated as patron: show login form.
  - If authenticated: show submission form.
- `POST /suggest-purchase/login`  
  - Validate credentials via Sierra.
  - Build patron actor and set `ds_actor` cookie.
- `POST /suggest-purchase/submit`  
  - Parse input, evaluate rules, persist request + events.
  - Redirect to confirmation.
- `GET  /suggest-purchase/confirmation?request_id=...`
- `GET  /suggest-purchase/my-requests`
  - Requires `suggest_purchase_view_own`.

### 6.2 “Smart bar” parsing (deterministic only)

Input label: **ISBN / ISSN / Title + Author**

Parsing rules (Phase 1):
1. If it matches an ISBN-10/13 (allow hyphens/spaces): normalize and validate checksum.
2. Else if it matches an ISSN: normalize and validate format.
3. Else if it looks like a URL: store as `url` (no fetching).
4. Else treat as free text:
   - Store full text as `title_author_text`
   - Optionally split on ` by ` (case-insensitive) into `title`, `author` when confident.

Key principle: **never delete user intent**—always preserve the raw input.

### 6.3 Rule evaluation UX

Rules run at submission time. The UI behavior depends on config:

- `mode=report`: submission succeeds; rule failures are written to `flags_json` for staff visibility.
- `mode=enforce`: submission is rejected with a single, clear reason.

---

## 7. Staff UX (Phase 1)

### 7.1 Staff pages
- `GET  /-/suggest-purchase/queue`
  - Filter by status, date, format, “flagged”.
- `GET  /-/suggest-purchase/request/<request_id>`
  - Show request details + full event log.
  - Staff actions: change status, add note, assign (optional).
- `POST /-/suggest-purchase/request/<request_id>/status`
- `POST /-/suggest-purchase/request/<request_id>/note`
- `GET  /-/suggest-purchase/export.csv?…`

### 7.2 Statuses (keep few, map to real work)

Phase 1 statuses:
- `new`
- `in_review`
- `ordered`
- `declined`
- `duplicate_or_already_owned`

Avoid “needs_more_info” until there is a defined communication channel back to patrons.

---

## 8. Data model (Phase 1 minimal)

### 8.1 Tables

#### `purchase_requests` (current state)
- `request_id` TEXT PK (UUID)
- `created_ts` TEXT (ISO 8601 UTC)
- `patron_record_id` INTEGER (Sierra)
- `raw_query` TEXT
- `parsed_kind` TEXT CHECK in (`isbn`,`issn`,`url`,`text`)
- `isbn` TEXT NULL
- `issn` TEXT NULL
- `url` TEXT NULL
- `title` TEXT NULL
- `author` TEXT NULL
- `title_author_text` TEXT NULL   -- preserves free-text parsing source
- `format_preference` TEXT NULL
- `patron_notes` TEXT NULL
- `status` TEXT NOT NULL DEFAULT 'new'
- `assigned_to` TEXT NULL         -- staff principal_id, optional
- `resolution_code` TEXT NULL
- `resolved_ts` TEXT NULL
- `flags_json` TEXT NULL          -- JSON array/dict of rule results / hints

Indexes:
- `(status, created_ts)`
- `(patron_record_id, created_ts)`

#### `request_events` (append-only audit log)
- `event_id` TEXT PK (UUID)
- `request_id` TEXT FK -> purchase_requests
- `ts` TEXT (ISO 8601 UTC)
- `actor_id` TEXT
- `event_type` TEXT CHECK in (`submitted`,`status_changed`,`note_added`)
- `payload_json` TEXT

Indexes:
- `(request_id, ts)`

#### `schema_migrations`
- `version` INTEGER PK
- `applied_ts` TEXT

This supports a tiny in-plugin migration runner.

### 8.2 Optional: patron cache (defer by default)

Do **not** create a patron cache table unless:
- rate-limiting requires more than `patron_record_id`, or
- you need to snapshot ptype/home library for later analysis, or
- you want to avoid repeat calls for ptype/home library on every submission.

If needed, add a minimal `patron_snapshot` table with:
- `patron_record_id` PK
- `ptype`
- `home_library`
- `last_refresh_ts`

No email storage by default.

---

## 9. Configuration (Phase 1 minimal)

All config lives in `datasette.yaml` under plugin config.

### 9.1 Sierra REST config
- `sierra_api_base`
- `sierra_client_key`
- `sierra_client_secret`

### 9.2 Suggest-a-purchase config
- `suggest_db_path` (default `suggest_purchase.db`)
- `rule_mode` = `report|enforce` (default `report`)
- `rules` (JSON object)
  - `allowed_ptypes` (optional list)
  - `min_account_age_days` (optional int)
  - `require_email_present` (optional bool; still does not store email)
  - `rate_limit` (object: `max`, `window_days`)

Defaults should be conservative but workable (example: `max=3`, `window_days=90`).

---

## 10. Security and abuse resistance (Phase 1 pragmatic)

- **Cookies:** rely on Datasette signed `ds_actor` cookie; set `HttpOnly`, `Secure`, `SameSite=Lax`.
- **CSRF:** all POST routes require CSRF token validation.
- **PII:** store patron record id only; avoid barcode/email persistence.
- **Logging:** log:
  - patron login success/failure (without credentials)
  - request submissions
  - staff status updates and notes
- **Abuse controls (lightweight):**
  - optional honeypot input on public form
  - optional per-IP rate cap (separate from patron rate cap)

---

## 11. Maintainability plan

### 11.1 Migration strategy
- Ship migrations as numbered SQL strings in code.
- On startup (or first write), open `suggest_purchase.db` and apply any missing migrations in order.
- Keep migrations small and reversible where practical.

### 11.2 Test strategy (Phase 1)
- Unit:
  - ISBN/ISSN parsing + normalization
  - rules evaluation
- Integration:
  - mock Sierra patron auth endpoint
  - submit request end-to-end (patron)
  - update request end-to-end (staff)

### 11.3 Observability
- Provide a staff-only “stats” page:
  - request counts by status
  - rule-failure frequency (from `flags_json`)
  - submissions per day/week

---

## 12. Roadmap (incremental, only after Phase 1 is stable)

### Phase 1.5 (small wins)
- “Already owned” hint for ISBN requests (Sierra lookup), recorded as a **flag** (not a blocker).
- `needs_more_info` status only if a communication mechanism is defined.

### Phase 2 (policy tightening)
- Switch default rule mode from `report` to `enforce` once staff confirms thresholds.
- Optional patron cache table for ptype/home library trend reporting.

### Phase 3 (bigger investments)
- Authority provider integrations + candidate selection UI
- Email verification *only if needed* (and only with clear privacy and comms requirements)
- Optional staff assignment workflows

---

## 13. Key simplifications vs the prior v1 draft

1. **No shared “core library” in Phase 1.** Keep code local until duplication appears.
2. **One supported deployment shape.** Avoid “one DB or two DB” as a design axis; pick a default.
3. **No local email storage.** Use patron record id as the join key back to Sierra.
4. **No authority-provider interface in Phase 1.** Parsing stays deterministic.
5. **No “needs_more_info” without patron messaging.** Reduce lifecycle states.

---

## 14. Open decisions (keep the list short)

1. Which Sierra patron auth endpoint and credential form will we support first?
2. Where do we reliably obtain:
   - ptype
   - home library
   - account created date
   - “email present” boolean
3. Default rule settings for CHPL (or your library):
   - allowed/blocked ptypes
   - min account age
   - rate limit window

These are the only Phase 1 decisions that materially affect implementation.

