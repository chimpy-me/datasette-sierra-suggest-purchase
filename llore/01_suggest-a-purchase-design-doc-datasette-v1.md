# Design Document: Suggest a Purchase (Datasette Plugin + Sierra ILS)

**Status:** Draft (integrated)  
**Primary users:** Library patrons (public). Secondary users: staff reviewers/admins.  
**Platform:** Datasette v1.x (ASGI) plugin-based app, local SQLite storage, Sierra ILS (REST API + optional direct DB reads).
**Related work:** `datasette-sierra-ils-auth` (staff login/RBAC) and `sierra-ils-utils` (Sierra REST client utilities).

**Datasette target:** Datasette **1.x** (1.0 alpha/stable series). This design explicitly targets the v1 plugin APIs and will avoid legacy 0.x compatibility shims.

## 0. Datasette v1 guardrails

This plugin will be written and tested against Datasette v1.x. Key implications (summarized from the v1 upgrade guides) are:

- **Query URLs:** use `/DB/-/query` endpoints (and their `.json` variants) rather than legacy `?sql=` database URLs.
- **Config vs metadata:** plugin configuration belongs in `datasette.yaml` (or `datasette.json`), not `metadata.yaml`. `metadata.yaml` is reserved for titles/descriptions/licenses only.
- **Metadata APIs:** avoid the removed `get_metadata()` hook and `datasette.metadata()` method; use the v1 metadata table APIs (`get_instance_metadata()`, `get_database_metadata()`, etc.) only if needed.
- **Permissions:** implement custom permissions as **actions** and check them using `await datasette.allowed(action=..., resource=..., actor=...)`. Prefer `permission_resources_sql()` over legacy `permission_allowed()`.
- **Testing:** prefer `ds.client` for HTTP tests; do not rely on deprecated `httpx.AsyncClient(app=...)` patterns.


---

## 1. Problem statement

Patrons need a modern, low-friction way to suggest titles the library does not own (or does not own in desired formats). Staff need a lightweight queue and triage workflow to review those requests in a manner consistent with the library’s selection criteria and public guidelines.

This project delivers:

1. Patron login using the Sierra REST API (via `sierra-ils-utils`), with **local caching** of patron attributes for eligibility checks, rate limiting, and analytics.
2. A patron-facing “smart” single input field (ISBN/ISSN/Title + Author) that parses intent and supports future authority lookups.
3. A staff-facing admin/review UI with RBAC, audit logging, and request lifecycle management.
4. Local persistence in SQLite, suitable for on-prem deployments (Podman/Docker) and for use in staff-facing Datasette instances.

---

## 2. Collection policy alignment

### 2.1 Public “Suggest a Purchase” guidelines (UI-facing)

The patron UI must present and align with these public guidelines:

- The library typically purchases titles **no more than three months in advance of publication**.
- Patrons are encouraged not to suggest **popular upcoming titles** (especially from bestselling authors) because staff already track them.
- Older titles may be less likely to be purchased; patrons should consider requesting via **SearchOhio** or **OhioLink** first.
- Patrons can review the **Collection Development Policy** for broader selection guidelines.
- Local and self-published authors are directed to separate guidelines.

(Extracted from the “Suggest a Purchase Guidelines” page provided in the screenshot.)

### 2.2 Collection Development Policy (staff-facing)

The review workflow should reflect that staff select materials using professional judgment and documented criteria. Factors include anticipated demand, community interests, strengths/weaknesses of existing collections, system-wide availability, physical space limitations, acquisitions procedures, and budgets. The policy explicitly lists **customer requests and recommendations** as one selection source, but those requests remain subject to the selection criteria. 【9†source】

Selection criteria include content quality/accuracy, cost in relation to use, reviews, current/anticipated appeal, format/accessibility considerations, local interest, relation to existing collection and community resources, significance of creator/publisher, audience suitability, and timeliness. 【9†source】

---

## 3. Goals and non-goals

### 3.1 Goals

- **Patron authentication** against Sierra REST APIs using `sierra-ils-utils`, designed to be modular.
- **Patron eligibility and throttling** via configurable rules (ptype, account age, email presence, rate limits).
- **Local persistence** of patron attributes (at login) and of purchase requests (at submission) in SQLite.
- **Staff review queue** with role-based access control, statuses, notes, and export capabilities.
- **Smart single input field** for request creation; deterministic parsing in Phase 1, authority integration later.
- **Security-first** handling of PII and operational audit logging.

### 3.2 Non-goals (initial phases)

- Automated acquisitions ordering, vendor integration, EDI, or MARC import pipelines.
- “AI-only” matching or decisions (AI is roadmap, not required for correctness).
- Enforcing all guideline nuances on day one (start with “report-only” policy mode and move to enforcement).

---

## 4. System overview

### 4.1 High-level architecture

**Datasette instance**
- Hosts one or more staff-facing databases (collection, patrons, etc.).
- Loads plugins:
  1. **Auth plugin** (refactor/extend `datasette-sierra-ils-auth`) providing *staff + patron login entrypoints* and the single `actor_from_request` implementation.
  2. **Suggest a Purchase plugin** providing patron UI + staff review UI + request persistence.

**Shared core library**
- A shared Python package (internal or published) used by both plugins for:
  - Sierra client adapters (backed by `sierra-ils-utils`)
  - session/cookie helpers
  - actor shaping (common contract)
  - rule evaluation engine
  - common SQLite helpers and audit/event primitives

> Note: Datasette supports authentication via the `actor_from_request()` hook and/or the built-in signed `ds_actor` cookie mechanism. To avoid ambiguity and plugin-order edge cases, we will keep a single “auth plugin” as the source of truth for setting the actor (preferably by setting the `ds_actor` cookie via `datasette.set_actor_cookie()`).

### 4.2 Data stores

- **Auth DB (SQLite):** staff users, roles/permissions, sessions, auth logs (existing plugin); plus patron cache tables.
- **Suggest DB (SQLite):** purchase requests, request lifecycle events, rate limit accounting, (future) email verification tokens.

Deployment may choose one DB or two DB files; the design supports both.

---

## 5. Identity, authentication, and authorization

### 5.1 Actor contract (shared)

All downstream plugins should rely on a stable actor schema:

```json
{
  "id": "staff:123" | "patron:456",
  "principal_type": "staff" | "patron",
  "principal_id": "123" | "456",
  "display": "Staff User Name" | "Patron",
  "email": "user@example.org",
  "roles": ["admin", "staff"] ,             // staff only
  "sierra": {
    "staff_username": "jsmith",             // staff only
    "patron_record_id": 123456,             // patron only
    "ptype": 3,
    "home_library": "MAIN"
  }
}
```

### 5.1.1 Datasette v1 integration notes (auth + permissions)

- **Preferred mechanism:** set the built-in signed `ds_actor` cookie using `datasette.set_actor_cookie(response, actor_dict)` and clear it using `datasette.delete_actor_cookie(response)`.
- **Logout:** prefer Datasette’s built-in `/-/logout` page for user-initiated sign-out (or provide a link to it).
- **Authorization checks:** the staff/admin UI routes in this plugin should use `await datasette.allowed(...)` with custom actions registered by the plugin.


### 5.2 Staff login (existing)

- Endpoint: Sierra `/v6/users/validate` (HTTP 204 on success).
- Local RBAC: roles, permissions, role_permissions, user_roles.
- Admin UI: manage users and roles.
- “Built-in admin” bypass remains optional for bootstrap.

### 5.3 Patron login (new entrypoint)

- Uses `sierra-ils-utils` to call Sierra’s patron login endpoint (exact endpoint depends on Sierra configuration; abstracted behind a `PatronAuthenticator` adapter).
- On successful login:
  - fetch patron attributes (email, ptype, created date, etc.)
  - cache locally in SQLite
  - establish patron session cookie


### 5.4 Authorization model (Datasette actions)

This plugin will define a small set of **Datasette actions** (v1 permissions model) and will use them consistently across UI routes and any write operations:

- `suggest-purchase-submit` — allow a patron to submit a request (typically restricted to authenticated patrons passing eligibility rules).
- `suggest-purchase-view-own` — allow a patron to view their own requests and statuses.
- `suggest-purchase-review` — staff can view the request queue and request details.
- `suggest-purchase-update` — staff can update statuses, add notes, and resolve requests.
- `suggest-purchase-admin` — staff can modify plugin configuration tables (if any), manage resolution codes, and access exports.

Mapping from staff roles (in the auth DB) to actions will be implemented via the shared auth core using `permission_resources_sql()`.

### 5.5 Eligibility rules engine (patrons)

Eligibility is a **configurable ruleset** evaluated either:
- at login (to warn early), and
- at submission (to enforce / re-check rate limits)

Rules are evaluated in one of two modes:
- `report` (Phase 1): user can submit; rule failures are recorded and can be flagged for staff review.
- `enforce` (Phase 2): rule failures block submission with actionable messaging.

Candidate rules:
- `allowed_ptypes` / `blocked_ptypes`
- `min_account_age_days`
- `require_email_present`
- `require_email_verified` (roadmap)
- `rate_limit(max, window_days)`
- optional: `no_blocks`, `home_library_allowlist`, etc.

---

## 6. Patron UX flows

### 6.1 Login and email check

1. Patron visits `/suggest-purchase` and is redirected to patron login if not authenticated.
2. After login, the app checks:
   - email present
   - (future) email verified
3. If email missing:
   - patron is told they must have an active email to submit
   - patron is directed to change/update it elsewhere (outside this app)
   - submission is blocked or allowed depending on rule mode

### 6.2 Create request: “smart bar” input

Single input field label: **“ISBN/ISSN/Title + Author”**.

Phase 1 parsing heuristics:
- URL → store as `url`, attempt lightweight extraction (optional)
- ISBN-10/13 → normalize and checksum validate
- ISSN → normalize and validate
- otherwise: treat as free text; attempt best-effort split (e.g., “title by author”)

User then provides optional fields:
- format preference (print, ebook, audiobook, DVD, etc.)
- notes/justification (optional)
- intended audience (optional)
- pickup branch (optional; informational)

### 6.3 Submission confirmation

Before submit, show:
- summarized parsed data
- guideline reminders (publication timing, etc.)
- a privacy note indicating what attributes are stored locally

On submit:
- create request row
- create event row (“submitted”)
- return confirmation page + reference ID

---

## 7. Staff/admin UX flows

### 7.1 Request queue

Staff-only routes guarded by Datasette actions (checked via `await datasette.allowed(...)`):
- list requests (filters: status, date range, format, flags, ptype, branch)
- open request detail view
- set status (e.g., New → In Review → Ordered → Declined → Duplicate/Already Owned)
- add staff notes and resolution codes
- export CSV for acquisitions workflows

### 7.2 Suggested statuses (initial)

- `new`
- `in_review`
- `needs_more_info` (optional, even if follow-up happens outside the app)
- `ordered`
- `declined`
- `duplicate_or_already_owned`

All transitions should emit `request_events` entries for auditability.

---

## 8. Data model (SQLite)

### 8.1 Patron cache tables (auth DB or shared DB)

**patrons**
- `patron_id` (PK; Sierra patron record id or internal UUID)
- `barcode_hash` (optional; avoid storing raw barcode)
- `ptype`
- `home_library`
- `email`
- `email_verified` (bool; roadmap)
- `email_verified_ts`
- `created_date` (for account age; sourced from DB or API)
- `last_login_ts`
- `last_attr_refresh_ts`
- `attributes_json` (raw snapshot for traceability)

**patron_rule_evaluations**
- `id` (PK)
- `patron_id`
- `evaluated_ts`
- `rule_results_json`
- `mode` (`report`/`enforce`)

### 8.2 Suggest a Purchase tables (suggest DB)

**purchase_requests**
- `request_id` (PK; UUID)
- `patron_id`
- `created_ts`
- `raw_query`
- `parsed_kind` (`isbn`/`issn`/`url`/`text`)
- `isbn`
- `issn`
- `url`
- `title`
- `author`
- `pub_date` (optional)
- `format_preference`
- `patron_notes`
- `status`
- `staff_assignee` (optional)
- `staff_notes` (optional)
- `resolution_code` (optional)
- `resolved_ts` (optional)
- `flags_json` (rule failures, guideline hints, etc.)

**request_events**
- `event_id` (PK)
- `request_id`
- `ts`
- `actor_id` (staff:<id> or patron:<id>)
- `event_type` (submitted, status_changed, note_added, etc.)
- `payload_json`

**rate_limit_index** (optional; can be derived via query)
- `patron_id`
- `window_start_ts`
- `count`

**email_verification_tokens** (roadmap)
- `token_id` (PK)
- `patron_id`
- `email`
- `token_hash`
- `created_ts`
- `expires_ts`
- `used_ts`

---

## 9. Configuration

### 9.1 Shared Sierra config (existing)

- `SIERRA_API_BASE`
- `SIERRA_CLIENT_KEY`
- `SIERRA_CLIENT_SECRET`

### 9.2 Auth plugin config (existing + additions)

- `SIERRA_AUTH_DB_PATH`
- `SIERRA_AUTH_COOKIE_NAME` (staff)
- `SIERRA_AUTH_COOKIE_MAX_AGE`
- `SIERRA_AUTH_ADMIN_PASSWORD` (optional)

Add patron counterparts:
- `SIERRA_PATRON_COOKIE_NAME`
- `SIERRA_PATRON_COOKIE_MAX_AGE`

### 9.3 Suggest plugin config

- `SUGGEST_DB_PATH`
- `SUGGEST_RULE_MODE` = `report|enforce`
- `SUGGEST_RULES_JSON` (ruleset)
- `SUGGEST_MAX_REQUESTS` and `SUGGEST_WINDOW_DAYS` (if not using JSON rules)
- `SUGGEST_REQUIRE_EMAIL` (bool; can be rule-driven)
- `SUGGEST_MIN_ACCOUNT_AGE_DAYS` (rule)
- `SUGGEST_ALLOWED_PTYPES` (rule)
- `SUGGEST_MAX_FUTURE_PUB_DAYS` (guideline enforcement; optional)

---

## 10. Authority matching and “purchasable” checks

### 10.1 Phase 1 (no AI)

- Deterministic parsing + checksum validation (ISBN/ISSN).
- Optional “already owned” hint:
  - if ISBN is present, query Sierra for holdings (via API or DB) and flag potential duplicates.
- Allow URL submissions, but treat as “needs review” unless an identifier is extracted.

### 10.2 Phase 2 (authority providers)

Introduce an interface:

- `AuthorityProvider.search(text) -> candidates`
- `AuthorityProvider.lookup(isbn/issn) -> record`

Wikidata is a candidate provider but may be complemented by pragmatic providers early. Keep a “select one candidate” UI step to maintain correctness even if ranking is imperfect.

### 10.3 Roadmap: AI assist

AI components are explicitly roadmap:
- better parsing of ambiguous text
- improved candidate ranking across authority providers
- dedupe suggestions (“we likely already own this edition”)

AI must remain **non-authoritative**; user selection or staff review remains the source of truth.

---

## 11. Security, privacy, and compliance

- Store the **minimum** patron PII needed (email + eligibility attributes). Prefer hashing barcodes; avoid storing passwords.
- Session cookies: `HttpOnly`, `Secure`, `SameSite=Lax` (or stricter where possible).
- CSRF protection for form posts.
- Audit logs for:
  - login attempts (existing staff auth log)
  - patron submissions
  - staff status changes and exports
- Database access controls:
  - staff-only views for patron-identifying data
  - optional “redaction” view for reporting

---

## 12. Observability and operations

- Structured logs for auth, request submissions, and staff actions.
- Admin page showing:
  - request counts by time window
  - rule failure rates (useful for tuning)
- Backup strategy:
  - SQLite DB files included in existing backup regime (restic/etc.)
  - periodic integrity checks (`PRAGMA integrity_check`)

---

## 13. Testing strategy

- Unit tests:
  - rules engine (ptype, account age, email present, rate limits)
  - parsing and normalization for ISBN/ISSN/URL/text
  - actor shaping
- Integration tests:
  - mock Sierra endpoints (`/users/validate`, patron login)
  - Datasette route tests (login, submit request, staff review)
- Migration tests:
  - schema upgrades for auth DB and suggest DB

---

## 14. Open decisions and next inputs

To finalize Phase 1 implementation details, confirm:

1. **Patron attribute sources**
   - Which fields and where: Sierra DB views vs REST endpoints for ptype, email, account creation date.
2. **Eligible patron types**
   - ptype allowlist/denylist.
3. **Rate limits**
   - defaults (e.g., 3 per 90 days) and whether keyed on patron record id vs barcode hash.
4. **Email update instructions**
   - the canonical “where to change email” workflow to link to in the UI.
5. **Admin roles**
   - which staff roles/permissions should grant request review/export.

---

## Appendix A: References

- Suggest a Purchase public guidelines (screenshot provided).
- Cincinnati & Hamilton County Public Library Collection Development Policy (PDF provided). 【9†source】
