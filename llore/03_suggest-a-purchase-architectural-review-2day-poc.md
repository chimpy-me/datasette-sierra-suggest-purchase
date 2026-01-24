# Suggest-a-Purchase (Datasette) — Architectural Pain Points + 2‑Day POC Cut Plan

**Context:** This review assesses the *Design Document v2* for “Suggest a Purchase” (Datasette v1 + Sierra ILS) and recommends a sharply simplified proof-of-concept that can be demoed in ~2 days by a skilled developer. It prioritizes **patron submission** and a **very lightweight staff review flow**, while explicitly **deferring the “smart bar”** and other time-consuming components. 【4†source】

---

## 1) Executive summary (what will slow you down vs. what ships fast)

### Biggest schedule risks for a 2‑day demo
1. **Sierra patron authentication variability**  
   The doc intentionally leaves open “which Sierra patron auth endpoint and credential form” is first supported. That’s the single most important “unknown unknown” for a 48‑hour POC. 【4†source】

2. **Auth boundary between “auth plugin” and “suggest plugin”**  
   The design keeps *actor_from_request* centralized in the existing auth plugin, while the suggest plugin sets the `ds_actor` cookie. That’s a good direction long-term, but the integration detail can still bite (cookie shape, same-site/secure flags, and how staff vs patron identities interact). 【4†source】

3. **CSRF + cookie security on custom POST routes**  
   Correct CSRF enforcement plus secure cookie behavior is non-negotiable on public forms, but it adds complexity and test surface area. 【4†source】

4. **Building custom staff UI vs. using Datasette primitives**  
   Fully custom queue/detail pages with filtering/export can consume a disproportionate amount of time if you build bespoke UI in Phase 1. The doc suggests custom staff pages; for a 2‑day POC, lean harder on Datasette’s built-in table browsing and CSV export. 【4†source】

### Recommended 2‑day POC shape
- **Patron can:** login → submit a request with *free-text only* → see confirmation → view “my requests”. 【4†source】
- **Staff can:** view all requests in Datasette’s table UI and update status via a single minimal form (or via an “update” route).  
- **Defer:** smart-bar parsing/normalization, rules engine (beyond a trivial cap), request_events auditing (optional), assignment workflow, advanced queue filters, custom export screen. 【4†source】

---

## 2) Architectural pain points (why they matter)

### 2.1 Sierra auth is the critical-path dependency
**Why it’s painful:** The doc lists Sierra auth as an open decision and implies it may vary by configuration (barcode/PIN, etc.). 【4†source】  
**What can go wrong quickly:**
- Endpoint discovery/permissions differences between environments
- Multi-step flows (PIN change, blocked accounts)
- “Email present” / “account age” fields needing different endpoints/fields than expected 【4†source】

**Mitigation for POC:** Implement *one* auth flow and treat every other eligibility rule as Phase 1.5/2. Keep the patron actor minimal: patron_record_id, ptype, home_library if easily retrieved; otherwise defer ptype/home_library. 【4†source】

### 2.2 Dual “principal types” in one cookie requires careful separation
The doc defines a patron actor schema and keeps staff actor unchanged. 【4†source】  
**Pain point:** If staff use the same Datasette instance, you must ensure:
- Staff can still authenticate as staff without being overwritten by patron cookie writes
- Patron routes never grant staff-only capabilities
- “View own submissions” correctly constrains by patron_record_id

**Mitigation for POC:**
- Use a **dedicated Datasette instance** for this workflow as the doc recommends. 【4†source】
- Keep staff access as a separate login path and never set a staff actor from patron login routes.

### 2.3 “Smart bar” parsing is deceptively expensive
Even “deterministic” parsing (ISBN/ISSN checksum validation, URL detection, title/author splitting) is time-consuming to implement correctly and test. 【4†source】  
**Mitigation for POC:** Accept free-text only, store `raw_query`, and keep all parsing fields null. Add parsing later behind feature flag.

### 2.4 Rules engine and flags_json are a “small framework” in disguise
The design supports `mode=report|enforce`, multiple rule types, and storing evaluation output. 【4†source】  
**Pain point:** Once you implement a rules engine, you now have:
- Configuration validation
- Deterministic evaluation
- UX semantics (“reject with one clear reason”)
- Test matrix across modes/rules

**Mitigation for POC:** Implement only one rule:
- **Patron-authenticated required** (already needed)
- Optional: **simple rate limit** (max N requests per patron in last X days) using a single SQL query, no flags_json.  
Defer `flags_json` until staff confirms desired policies. 【4†source】

### 2.5 Migration runner inside the plugin is extra moving parts
A deterministic in-plugin migration runner is maintainable long-term, but for a 2‑day demo it can consume time (and debugging) that you could avoid by shipping a pre-created SQLite file or a single `CREATE TABLE IF NOT EXISTS` on startup. 【4†source】

**Mitigation for POC:** For the demo:
- Use a minimal “ensure schema” step on startup, and add the migration runner after the demo.

### 2.6 Custom staff queue/detail UI can balloon
The document proposes staff queue, request detail page, actions, and CSV export screen. 【4†source】  
**Pain point:** UI time, permissions wiring, and filtering logic (status/date/flagged) can exceed value for the demo.

**Mitigation for POC:**  
- Staff review = browsing `purchase_requests` table in Datasette UI.  
- CSV export = Datasette’s existing CSV output for table/query.

---

## 3) 2‑Day POC: minimum viable scope

### 3.1 Features that MUST be in the demo
**Patron**
- Patron login against Sierra (one supported method). 【4†source】
- Submit request (free-text field + optional patron notes + optional format preference). 【4†source】
- Confirmation page.
- “My requests” page filtered by patron_record_id. 【4†source】

**Staff**
- View all requests (Datasette table UI is acceptable for POC).
- Update status (single minimal mechanism).

### 3.2 Explicit deferrals (to keep the demo realistic)
- Smart bar parsing/validation (ISBN/ISSN/URL); treat everything as text. 【4†source】
- Full rules framework (`report|enforce`, flags_json). 【4†source】
- request_events table (optional—see below). 【4†source】
- Assignment workflow.
- Custom queue UI with filtering and “flagged” views.
- “Already owned” checks and authority integrations. 【4†source】

---

## 4) POC data model (minimal, demo-safe)

### Option A (fastest): single table only
`purchase_requests`
- `request_id` TEXT PK (uuid)
- `created_ts` TEXT (UTC ISO8601)
- `patron_record_id` INTEGER
- `raw_query` TEXT
- `format_preference` TEXT NULL
- `patron_notes` TEXT NULL
- `status` TEXT NOT NULL DEFAULT 'new'
- `staff_notes` TEXT NULL
- `updated_ts` TEXT NULL

Indexes:
- `(status, created_ts)`
- `(patron_record_id, created_ts)` 【4†source】

**Pros:** fastest, simplest, easy demo  
**Cons:** less auditability

### Option B (still small): add request_events
If you want a credible audit trail, keep the doc’s `request_events` table but restrict event types to `submitted`, `status_changed`, `note_added`. 【4†source】

**Recommendation for 2-day demo:** Option A unless you already have strong audit expectations.

---

## 5) POC staff review: simplest workable implementation

### Minimal review model
- Staff uses Datasette UI to view `purchase_requests`.
- Provide one custom POST route:
  - `POST /-/suggest-purchase/request/<request_id>/update`
  - fields: `status`, `staff_notes`
- That route performs authorization using a single action check (e.g., `suggest_purchase_update`). 【4†source】

### Why this is enough to “demo working”
- Staff sees requests appear immediately.
- Staff changes status and adds notes.
- Patron can see status changes reflected on “my requests”.

---

## 6) Security / abuse: what to do now vs later

### Must-do for public-facing demo
- Secure signed `ds_actor` cookie behavior (`HttpOnly`, `Secure`, `SameSite=Lax`). 【4†source】
- CSRF validation on all POST routes. 【4†source】
- Store minimal PII: patron_record_id only. 【4†source】
- Logging of login + submissions (no credentials). 【4†source】

### Defer unless you see active abuse
- Honeypot field
- Per-IP rate caps
- Advanced eligibility checks requiring extra Sierra calls (email present, account age) 【4†source】

---

## 7) Concrete 2‑day implementation plan (developer checklist)

### Day 1 (core flow)
1. **Schema creation** (Option A) on startup.
2. **Patron login route**:
   - Validate via Sierra
   - Build patron actor (id, principal_type, principal_id, sierra.patron_record_id)
   - Set `ds_actor` cookie. 【4†source】
3. **Patron submission route**:
   - Insert into `purchase_requests`
   - Redirect to confirmation
4. **My requests page**:
   - SQL query filtered by `patron_record_id` from actor
   - Simple HTML template

### Day 2 (staff + hardening)
1. **Staff authorization action wiring**:
   - `suggest_purchase_review`, `suggest_purchase_update` (minimal set) 【4†source】
2. **Staff update route** (status + staff notes)
3. **Demo polish**:
   - Basic form validation
   - Clear success/failure messaging
4. **Operational notes**:
   - Document how to run locally, required secrets, and demo steps

---

## 8) What to add immediately after the demo (Phase 1.5)

In order of impact/effort:
1. **“Already owned” hint for ISBN** (as a staff-visible flag, not a blocker). 【4†source】
2. **Basic request_events** for auditability. 【4†source】
3. **Introduce rule_mode=report** with a small number of rules once staff agrees on thresholds. 【4†source】
4. **Upgrade “smart bar” incrementally**:
   - Start with ISBN normalization only
   - Then ISSN
   - Then URL classification
   - Then title/author split heuristics 【4†source】

---

## 9) Key decisions you must make *before* coding (to avoid churn)

The doc’s “Open decisions” section is correct: these can break timelines if left unclear. 【4†source】

For a 2-day POC, decide:
1. **Exact Sierra patron auth method** (endpoint + required credentials).
2. **Whether ptype/home_library is required in POC** (recommend: not required).
3. **Rate limit on/off** (recommend: off for demo unless required by stakeholders).

---

## 10) Recommended “dumbed-down” UX for the demo

### Patron form fields
- “What would you like us to consider purchasing?” (free text)
- Optional: Format preference (dropdown)
- Optional: Notes (textarea)
- Submit

### Staff review
- Datasette table list
- Status update form on request detail page

This preserves the “wildly cool” omni-bar vision as a Phase 2 enhancement without blocking early value. 【4†source】
