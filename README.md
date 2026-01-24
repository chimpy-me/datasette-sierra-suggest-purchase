# datasette-suggest-purchase

A Datasette plugin that allows library patrons to suggest purchases, with Sierra ILS integration for patron authentication.

**Status:** POC complete + suggest-a-bot Phase 0 infrastructure (75 tests passing)

## Quick Start

```bash
# Install dependencies
uv sync --dev && uv pip install -e .

# Start development server (initializes DB, starts fake Sierra, runs Datasette)
./scripts/dev.sh
```

Then open:
- **Patron UI:** http://127.0.0.1:8001/suggest-purchase
- **Staff view:** http://127.0.0.1:8001/suggest_purchase/purchase_requests

### Test Patrons

| Barcode        | PIN  | Name            |
|----------------|------|-----------------|
| 12345678901234 | 1234 | Test Patron One |
| 23456789012345 | 5678 | Test Patron Two |

## Features

### Patron
- Login with library card + PIN (Sierra ILS authentication)
- Submit purchase suggestion (free text + optional format/notes)
- View confirmation
- View "My Requests" with status updates

### Staff
- View all requests in Datasette table UI
- Update request status and add notes
- CSV export via Datasette
- Full audit trail via `request_events` table

### suggest-a-bot (Background Processor)

Automated background processor that enriches patron suggestions:

```bash
# Process all pending requests once
python -m suggest_a_bot --db suggest_purchase.db --once

# Dry run (show what would be processed)
python -m suggest_a_bot --db suggest_purchase.db --dry-run

# Run as daemon
python -m suggest_a_bot --db suggest_purchase.db --daemon
```

**Processing pipeline (in development):**
1. **Catalog lookup** - Check Sierra for existing holdings
2. **Consortium check** - Query OhioLINK/SearchOHIO for availability
3. **Input refinement** - Use LLM to normalize patron input
4. **Selection guidance** - Generate staff-facing assessment
5. **Automatic actions** - Place holds, flag duplicates (configurable)

See `llore/04_suggest-a-bot-design.md` for full design.

## Project Structure

```
src/datasette_suggest_purchase/
    plugin.py               # Main plugin with routes
    templates/              # Jinja2 templates
    migrations/             # SQL migrations

src/suggest_a_bot/          # Background processor
    config.py               # YAML config loading
    models.py               # Data models + DB operations
    pipeline.py             # Processing stages
    run.py                  # CLI entry point

scripts/
    dev.sh                  # One-command dev startup
    init_db.py              # Database initialization + migrations
    fake_sierra.py          # Fake Sierra API for local dev

tests/                      # 75 tests (unit + integration)
llore/                      # Design documents
```

## Configuration

Configuration is in `datasette.yaml`:

```yaml
plugins:
  datasette-suggest-purchase:
    sierra_api_base: "http://127.0.0.1:9009/iii/sierra-api"
    sierra_client_key: "${SIERRA_CLIENT_KEY}"
    sierra_client_secret: "${SIERRA_CLIENT_SECRET}"
    suggest_db_path: "suggest_purchase.db"
    rule_mode: "report"

    # suggest-a-bot configuration
    bot:
      enabled: true
      schedule: "*/15 * * * *"
      stages:
        catalog_lookup: true
        consortium_check: false
        input_refinement: false
        selection_guidance: false
        automatic_actions: false
```

## Development

```bash
# Run tests
.venv/bin/pytest tests/ -v

# Lint and format
uv run ruff check .
uv run ruff format .

# Initialize/migrate database
python scripts/init_db.py --db suggest_purchase.db
```

## Status Workflow

Requests flow through these statuses:
- `new` - Just received
- `in_review` - Being reviewed by staff
- `ordered` - Item ordered
- `declined` - Not purchasing
- `duplicate_or_already_owned` - Already in collection

Bot processing status:
- `pending` - Awaiting bot processing
- `processing` - Currently being processed
- `completed` - Bot processing finished
- `error` - Bot encountered an error
- `skipped` - Skipped by bot

## License

MIT
