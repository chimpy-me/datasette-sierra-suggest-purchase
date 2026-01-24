# suggest-a-bot: Automated Purchase Suggestion Processing

**Status:** Proposed
**Priority:** Top-line feature
**Last updated:** 2026-01-24

---

## 1. Vision

NOTE: This should be it's own repo and package, e.g.,
`/chimpy-me/sierra-suggest-a-bot` but lets define the design here first, and possibly develop in this monorepo initially.

**suggest-a-bot** is a periodic background processor that automatically enriches, validates, and triages patron purchase suggestions. It runs on modest hardware using a local LLM capable of tool calls, enabling intelligent automation without cloud dependencies.

### Core value proposition
- **Reduce staff workload** by pre-processing suggestions before human review
- **Improve patron experience** by providing faster feedback and automatic holds
- **Surface actionable intelligence** for subject selectors using collection guidelines

---

## 2. Processing pipeline (simple to complex)

suggest-a-bot processes suggestions through a series of increasingly sophisticated checks. Each stage enriches the request record with findings for staff review.

### Stage 1: Catalog lookup (local holdings check)
**Goal:** Determine if we already own the requested item (or something very similar).

- Parse patron input for identifiers (ISBN, title/author)
- Query Sierra catalog via API or direct DB read
- Record findings:
  - `catalog_match`: exact/partial/none
  - `catalog_holdings`: list of matching bib records with availability
  - `catalog_checked_ts`: timestamp

**Outcome:** Flag potential duplicates; suggest "already owned" resolution for exact matches.

### Stage 2: Consortium availability (OhioLINK / SearchOHIO)
**Goal:** Check if the item is available through resource sharing before purchasing.

- Query OhioLINK/SearchOHIO APIs (or scrape if no API)
- Record findings:
  - `consortium_available`: boolean
  - `consortium_sources`: list of lending libraries
  - `consortium_checked_ts`: timestamp

**Outcome:** Offer to place ILL hold for patron if available; deprioritize purchase if widely held.

### Stage 3: Input refinement and authority matching
**Goal:** Normalize messy patron input into structured bibliographic data.

- Use LLM with tool calls to:
  - Parse ambiguous "title by author" strings
  - Search authority sources (WorldCat, Open Library, Google Books API)
  - Resolve to a canonical work/edition
- Record findings:
  - `refined_title`, `refined_author`, `refined_isbn`
  - `authority_source`: where the match came from
  - `confidence_score`: how confident the bot is in the match

**Outcome:** Cleaner data for staff review; better catalog/consortium lookups.

### Stage 4: Selection guidance (LLM-assisted)
**Goal:** Provide subject selectors with relevant context based on collection guidelines.

- Feed the request + collection development policy to LLM
- Generate a brief assessment:
  - Does this fit our collection scope?
  - Is this a popular/bestselling author we'd track anyway?
  - Publication date considerations (too far out? too old?)
  - Format availability (ebook vs print vs audio)
  - Local interest indicators
- Record findings:
  - `bot_assessment`: structured JSON with recommendations
  - `bot_notes`: human-readable summary for staff

**Outcome:** Staff see a pre-written "first pass" evaluation; speeds triage.

### Stage 5: Automatic actions (with guardrails)
**Goal:** Take action on clear-cut cases without human intervention.

Potential automatic actions (all configurable, disabled by default):
- **Auto-hold:** If item exists in consortium, place ILL hold for patron
- **Auto-decline:** If exact match in catalog, mark as "duplicate_or_already_owned"
- **Auto-flag:** If item matches "popular upcoming titles" pattern, flag for review

All automatic actions:
- Are logged to `request_events` with full audit trail
- Can be overridden by staff
- Respect a `bot_action_mode` config: `suggest` (default) | `auto`

---

## 3. Architecture

### 3.1 Runtime model

```
┌─────────────────────────────────────────────────────────┐
│                    suggest-a-bot                         │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
│  │ Scheduler │───▶│ Pipeline │───▶│ Local LLM        │  │
│  │ (cron)   │    │ Runner   │    │ (tool-calling)   │  │
│  └──────────┘    └────┬─────┘    └──────────────────┘  │
│                       │                                  │
│         ┌─────────────┼─────────────┐                   │
│         ▼             ▼             ▼                   │
│  ┌───────────┐ ┌───────────┐ ┌───────────────┐         │
│  │ Sierra    │ │ OhioLINK  │ │ Authority     │         │
│  │ Catalog   │ │ SearchOHIO│ │ Sources       │         │
│  └───────────┘ └───────────┘ └───────────────┘         │
└─────────────────────────────────────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ suggest_purchase│
              │     .db         │
              └─────────────────┘
```

### 3.2 Deployment options

**Option A: Embedded (simplest)**
- Run as a background task within the Datasette process
- Use `asyncio` scheduler (e.g., `apscheduler` or simple loop)
- Pros: Single process, no extra infrastructure
- Cons: Ties up Datasette resources during processing

**Option B: Standalone daemon (recommended for production)**
- Separate Python process with its own scheduler
- Reads/writes to the same `suggest_purchase.db`
- Can run on different hardware (e.g., machine with GPU)
- Pros: Decoupled, scalable, can use beefier LLM
- Cons: More moving parts

**Option C: Cron job**
- Simple `python -m suggest_a_bot.run` invoked by system cron
- Processes all pending suggestions, then exits
- Pros: Simplest ops, no daemon management
- Cons: Less responsive (batch processing only)

### 3.3 LLM requirements

**Minimum viable:**
- Local model with tool/function calling support
- Examples: Llama 3.x, Mistral, Qwen with tool calling
- Can run on CPU (slower) or modest GPU (4-8GB VRAM)

**Tool calling capabilities needed:**
- `search_catalog(query)` - search Sierra holdings
- `search_consortium(query)` - search OhioLINK/SearchOHIO
- `search_authority(query)` - search WorldCat/Open Library
- `lookup_isbn(isbn)` - get bibliographic details
- `assess_selection(title, author, request_context)` - evaluate against guidelines

**Inference framework options:**
- `llama.cpp` (via `llama-cpp-python`)
- `vLLM` (if GPU available)
- `Ollama` (easy local setup)
- Remote API as fallback (OpenAI, Anthropic, etc.)

---

## 4. Data model additions

### 4.1 New columns on `purchase_requests`

```sql
-- Bot processing status
bot_status TEXT DEFAULT 'pending'
    CHECK (bot_status IN ('pending', 'processing', 'completed', 'error', 'skipped')),
bot_processed_ts TEXT,
bot_error TEXT,

-- Stage 1: Catalog lookup
catalog_match TEXT CHECK (catalog_match IN ('exact', 'partial', 'none')),
catalog_holdings_json TEXT,  -- JSON array of matching bibs
catalog_checked_ts TEXT,

-- Stage 2: Consortium availability
consortium_available INTEGER,  -- 0/1
consortium_sources_json TEXT,  -- JSON array of lending libraries
consortium_checked_ts TEXT,

-- Stage 3: Input refinement
refined_title TEXT,
refined_author TEXT,
refined_isbn TEXT,
authority_source TEXT,
refinement_confidence REAL,

-- Stage 4: Selection guidance
bot_assessment_json TEXT,  -- structured recommendations
bot_notes TEXT,            -- human-readable summary

-- Stage 5: Automatic actions taken
bot_action TEXT,           -- 'hold_placed', 'auto_declined', etc.
bot_action_ts TEXT
```

### 4.2 New table: `bot_runs`

Track each processing run for observability.

```sql
CREATE TABLE bot_runs (
    run_id TEXT PRIMARY KEY,
    started_ts TEXT NOT NULL,
    completed_ts TEXT,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    requests_processed INTEGER DEFAULT 0,
    requests_errored INTEGER DEFAULT 0,
    config_snapshot_json TEXT,  -- config used for this run
    error_message TEXT
);
```

### 4.3 Event types for `request_events`

Add new event types for bot actions:
- `bot_catalog_checked`
- `bot_consortium_checked`
- `bot_refined`
- `bot_assessed`
- `bot_action_taken`
- `bot_error`

---

## 5. Configuration

```yaml
plugins:
  datasette-suggest-purchase:
    # ... existing config ...

    # suggest-a-bot configuration
    bot:
      enabled: true
      schedule: "*/15 * * * *"  # every 15 minutes (cron syntax)

      # Processing stages (enable/disable individually)
      stages:
        catalog_lookup: true
        consortium_check: true
        input_refinement: true
        selection_guidance: true
        automatic_actions: false  # off by default

      # LLM configuration
      llm:
        provider: "ollama"  # ollama | llama_cpp | openai | anthropic
        model: "llama3.1:8b"
        base_url: "http://localhost:11434"
        # For cloud providers:
        # api_key_env: "OPENAI_API_KEY"

      # Automatic action settings (when enabled)
      auto_actions:
        hold_on_consortium_match: false
        decline_on_catalog_exact_match: false
        flag_popular_authors: true

      # Rate limiting
      max_requests_per_run: 50

      # Sierra catalog connection
      sierra:
        # Can reuse main Sierra config or override
        use_db_direct: false  # true = direct DB queries (faster)
        db_connection_string_env: "SIERRA_DB_URL"

      # Consortium APIs
      consortium:
        ohiolink_enabled: true
        searchohio_enabled: true
        # API keys if needed
```

---

## 6. Implementation phases

### Phase 0: Infrastructure (immediate)
- [ ] Add bot-related columns to schema (migration)
- [ ] Create `bot_runs` table
- [ ] Add bot event types to `request_events`
- [ ] Create basic CLI runner: `python -m suggest_a_bot.run`

### Phase 1: Catalog lookup (MVP)
- [ ] Implement Sierra catalog search (API first, DB later)
- [ ] Record findings in `catalog_*` columns
- [ ] Add "catalog match" indicator to staff UI
- [ ] Basic scheduling (cron or simple loop)

### Phase 2: Consortium availability
- [ ] Research OhioLINK/SearchOHIO APIs
- [ ] Implement consortium search
- [ ] Record findings in `consortium_*` columns
- [ ] Add consortium status to staff UI

### Phase 3: LLM integration
- [ ] Set up local LLM with tool calling
- [ ] Implement input refinement stage
- [ ] Implement selection guidance stage
- [ ] Add bot assessment to staff UI

### Phase 4: Automatic actions
- [ ] Implement hold placement (ILL integration)
- [ ] Implement auto-decline for duplicates
- [ ] Add configuration UI for action settings
- [ ] Comprehensive audit logging

---

## 7. Open questions

1. **Sierra catalog access:** REST API only, or direct PostgreSQL for performance?
2. **OhioLINK/SearchOHIO:** Do they have APIs, or will we need to scrape?
3. **ILL integration:** What's the mechanism to place holds programmatically?
4. **LLM hosting:** Run locally on same box, or dedicated inference server?
5. **Collection guidelines:** Do we have these in machine-readable form, or PDF only?

---

## 8. Success metrics

- **Time to first response:** How quickly do suggestions get bot-processed?
- **Duplicate detection rate:** What % of suggestions are flagged as already owned?
- **Consortium hit rate:** What % are available through resource sharing?
- **Staff time saved:** Reduction in manual research per suggestion
- **Patron satisfaction:** Faster holds, better communication

---

## Appendix A: Tool schemas (draft)

```python
TOOLS = [
    {
        "name": "search_catalog",
        "description": "Search the library catalog for matching titles",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (title, author, ISBN)"},
                "search_type": {"type": "string", "enum": ["keyword", "title", "author", "isbn"]}
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_consortium",
        "description": "Search OhioLINK/SearchOHIO for availability at other libraries",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "author": {"type": "string"},
                "isbn": {"type": "string"}
            }
        }
    },
    {
        "name": "assess_for_purchase",
        "description": "Evaluate a title against collection development guidelines",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "author": {"type": "string"},
                "format": {"type": "string"},
                "publication_date": {"type": "string"},
                "patron_notes": {"type": "string"}
            },
            "required": ["title"]
        }
    }
]
```

---

## Appendix B: Example bot output

For a patron request: `"The Women by Kristin Hannah"`

```json
{
  "catalog_match": "none",
  "catalog_holdings_json": [],
  "consortium_available": true,
  "consortium_sources_json": [
    {"library": "Columbus Metropolitan", "status": "available"},
    {"library": "Cuyahoga County", "status": "available"}
  ],
  "refined_title": "The Women: A Novel",
  "refined_author": "Kristin Hannah",
  "refined_isbn": "9781250178633",
  "authority_source": "worldcat",
  "refinement_confidence": 0.95,
  "bot_assessment_json": {
    "recommendation": "purchase",
    "confidence": "high",
    "reasoning": [
      "Bestselling author with strong local demand",
      "New release (2024) within acquisition window",
      "Available in multiple formats",
      "Not currently in catalog"
    ],
    "format_suggestion": "print + ebook",
    "priority": "high"
  },
  "bot_notes": "Kristin Hannah is a bestselling author. This 2024 release is widely held in the consortium but not in our catalog. Recommend purchase in print and ebook formats."
}
```
