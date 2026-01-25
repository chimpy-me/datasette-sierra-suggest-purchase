# datasette-suggest-purchase

A Datasette plugin that allows library patrons to suggest purchases, with Sierra ILS integration for patron authentication.

**Status:** POC complete + suggest-a-bot M1 evidence extraction (233 tests passing)

## Quick Start

### Option 1: Native Development

```bash
# Install dependencies
uv sync --dev && uv pip install -e .

# Start development server (initializes DB, starts fake Sierra, runs Datasette)
./scripts/dev.sh
```

### Option 2: Container Development (Podman)

```bash
# Build and start containers
./scripts/container-dev.sh --build

# Or just start (if already built)
./scripts/container-dev.sh

# View logs
./scripts/container-dev.sh logs

# Stop containers
./scripts/container-dev.sh down
```

Then open:
- **Patron UI:** http://127.0.0.1:8001/suggest-purchase
- **Staff login:** http://127.0.0.1:8001/suggest-purchase/staff-login
- **Staff view:** http://127.0.0.1:8001/suggest_purchase/purchase_requests

### Test Accounts

**Patrons** (Sierra/library card login):

| Barcode        | PIN  | Name            |
|----------------|------|-----------------|
| 12345678901234 | 1234 | Test Patron One |
| 23456789012345 | 5678 | Test Patron Two |

**Staff** (local account, set via environment):

```bash
# Set before starting the server
export STAFF_ADMIN_PASSWORD=yourpassword

# Optional customization
export STAFF_ADMIN_USERNAME=admin      # default: admin
export STAFF_ADMIN_DISPLAY_NAME=Admin  # default: Administrator
```

The admin account is automatically created/updated on startup when `STAFF_ADMIN_PASSWORD` is set.

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

**Processing pipeline:**
0. **Evidence extraction** ✅ - Extract ISBN/ISSN/DOI/URLs, build structured evidence packet
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
    identifiers.py          # ISBN/ISSN/DOI/URL extraction
    evidence.py             # Evidence packet builder
    run.py                  # CLI entry point

scripts/
    dev.sh                  # Native dev startup
    container-dev.sh        # Container dev startup (podman-compose)
    init_db.py              # Database initialization + migrations
    fake_sierra.py          # Fake Sierra API for local dev

containers/
    datasette/Containerfile # Datasette + plugin image
    fake-sierra/Containerfile # Mock Sierra API image

tests/                      # 233 tests (unit + integration)
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
