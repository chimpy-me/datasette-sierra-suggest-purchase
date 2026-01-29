# Security & Compliance Remediation Plan

Date: 2026-01-29
Owner: Security/Compliance + Engineering
Scope: Datasette suggest-a-purchase (plugin + suggest-a-bot)
Status: Implemented on branch `security-remediation-sprints`

This document provides:

- A series of commits with concrete change bundles
- Related tests for each commit
- A sprint plan to implement all remediations with strong test coverage

## Guiding Principles

- Minimize patron PII in cookies and outbound requests.
- Prefer defense-in-depth: CSRF + auth checks + rate limiting.
- Treat all patron input as untrusted (XSS/CSV injection/PII leakage).
- Ship with tests for each fix (unit + integration).
- Keep security controls configurable and well documented.

## Proposed Commit Series (with Tests)

Commit 1: CSRF enforcement for staff routes

- Code changes
  - Remove staff routes from `skip_csrf` exemptions.
  - Add CSRF tokens to any staff POST forms (staff login and staff update).
  - Ensure staff login still works with CSRF token on GET->POST flow.
- Tests
  - Integration: POST staff update without CSRF returns 403.
  - Integration: POST staff update with CSRF succeeds.
  - Integration: staff login flow includes CSRF token and succeeds.
- Notes
  - If staff login must remain CSRF-exempt, add a dedicated anti-CSRF measure (e.g., double-submit token) and test it.

Commit 2: Rate limiting for patron and staff login

- Code changes
  - Implement a shared login rate limiter (per-IP + per-username/barcode).
  - Enforce existing `rules` config (e.g., max attempts within window).
  - Add clear error messaging and incremental backoff.
- Tests
  - Unit: rate limiter counts and expiry.
  - Integration: multiple failed logins trigger lockout/slowdown.
  - Integration: successful login resets/clears counters.

Commit 3: Minimize ds_actor PII

- Code changes
  - Reduce patron cookie payload to minimal identifiers (patron_record_id only).
  - Store display name/ptype/home_library server-side if required (or fetch on demand).
  - Ensure staff cookie does not include extra sensitive fields.
- Tests
  - Unit: actor cookie contains only expected keys.
  - Integration: patron flows still work with minimal actor.
  - Integration: no PII present in cookie for patron.

Commit 4: Confirmation ownership check

- Code changes
  - Restrict confirmation query to `request_id` + `patron_record_id`.
  - Return 404/redirect if not owned.
- Tests
  - Integration: patron cannot access another patron’s confirmation by ID.
  - Integration: owner access still works.

Commit 5: Audit trail for patron/staff actions

- Code changes
  - Write `request_events` entries on submit, status change, note add.
  - Include actor_id for patron/staff, and minimal payload.
- Tests
  - Integration: submit creates `submitted` event.
  - Integration: staff update creates `status_changed` and/or `note_added` event.
  - Unit: event payload schema (keys only, no PII).

Commit 6: Third‑party data sharing controls (Open Library)

- Code changes
  - Add PII scrubber for outbound Open Library queries (strip emails, phone numbers, library card patterns).
  - Add explicit configuration gate for enrichment + notice in UI.
  - Provide a safety log when scrubbing occurs (no raw data in logs).
- Tests
  - Unit: scrubber removes common PII patterns.
  - Integration: enrichment disabled by config (no HTTP calls).
  - Unit: scrubber is applied to outbound queries.

Commit 7: Secure cookie defaults + HTTPS requirement

- Code changes
  - Enable `secure=True` for cookies when `datasette` is in HTTPS or config flag set.
  - Add startup check or config warning if running in production without HTTPS.
- Tests
  - Unit: cookie flags include Secure when HTTPS enabled.
  - Integration: cookie flags are correct under config.

Commit 8: Staff logout + session revocation

- Code changes
  - Add `/suggest-purchase/staff-logout` route to clear staff cookie.
  - Optionally rotate/blacklist cookies server-side (if feasible).
- Tests
  - Integration: staff logout clears cookie and blocks access.

Commit 9: CSV injection hardening

- Code changes
  - Sanitize exported CSV fields by prefixing dangerous values with `'`.
  - Apply to raw_query and notes fields.
- Tests
  - Unit: sanitizer transforms `=SUM(...)` to safe string.
  - Integration: CSV export contains sanitized fields.

Commit 10: Data retention policy + sample DB safety

- Code changes
  - Add retention config for purging old requests/events (manual command or scheduled job).
  - Remove or clearly mark `suggest_purchase.db` as fake sample data; add gitignore guidance.
- Tests
  - Unit: retention purge deletes only records older than threshold.
  - Integration: purge command leaves recent records intact.

## Sprint Plan (Suggested Sequence)

Sprint 1: Auth + CSRF Hardening

- Deliver commits 1–3.
- Risks: CSRF changes can break login flows; cookie changes can break patron UX.
- Testing focus: integration tests for login and staff update flows.
- Definition of done: CSRF enforced, rate limits active, minimal cookie payload.

Sprint 2: Authorization + Audit

- Deliver commits 4–5.
- Risks: ownership checks may affect bookmarked confirmations.
- Testing focus: multi-user scenarios, event log correctness.
- Definition of done: strict ownership checks + full audit events.

Sprint 3: Third‑Party Sharing + Transport Security

- Deliver commits 6–7.
- Risks: Open Library integration might degrade; HTTPS detection may need environment-specific logic.
- Testing focus: PII scrubber unit tests, config-driven integration tests.
- Definition of done: PII scrubbed, enrichment gated, cookies secure over HTTPS.

Sprint 4: Operational Controls

- Deliver commits 8–10.
- Risks: CSV changes might surprise staff workflows; retention needs stakeholder alignment.
- Testing focus: CSV safety, retention safety, logout flows.
- Definition of done: logout flow working, CSV hardened, retention documented and tested.

## Test Strategy Summary

- Unit tests
  - Rate limiter, PII scrubber, cookie payload, CSV sanitizer.
- Integration tests
  - Patron login/submit/confirm ownership.
  - Staff login/update/logout with CSRF enforcement.
  - Audit trail event creation.
  - Open Library gating by config.

## Open Questions for Review

- Should staff login remain CSRF‑exempt, or can we require CSRF tokens for login forms?
  - They should not remain exempt; we can implement a double-submit token if needed.
- What is the acceptable retention window for patron requests and audit logs?
  - Suggested default: 1 year for requests, 3 years for audit logs; configurable.
- Are there legal requirements to avoid third‑party enrichment entirely unless explicitly opt‑in?
  - Table this for now; recommend opt-in by default with clear notice.
- Should staff sessions be server‑side and revocable, or is signed cookie sufficient?
  - Signed cookie is sufficient for now; consider server-side sessions in future iterations.
