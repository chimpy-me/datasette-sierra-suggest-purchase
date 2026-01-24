# datasette-suggest-purchase

A Datasette plugin that allows library patrons to suggest purchases, with Sierra ILS integration for patron authentication.

## Quick Start

```bash
# Install dependencies
uv sync --dev

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

## Project Structure

```
src/datasette_suggest_purchase/
    __init__.py
    plugin.py           # Main plugin with routes
    templates/          # Jinja2 templates
scripts/
    dev.sh              # One-command dev startup
    init_db.py          # Database initialization
    fake_sierra.py      # Fake Sierra API for local dev
tests/
    unit/
    integration/
```

## Features (POC Scope)

### Patron
- Login with library card + PIN
- Submit purchase suggestion (free text + optional format/notes)
- View confirmation
- View "My Requests" with status

### Staff
- View all requests in Datasette table UI
- Update request status via POST route
- CSV export via Datasette

## Configuration

Configuration is in `datasette.yaml`:

```yaml
plugins:
  datasette-suggest-purchase:
    sierra_api_base: "${SIERRA_API_BASE}"
    sierra_client_key: "${SIERRA_CLIENT_KEY}"
    sierra_client_secret: "${SIERRA_CLIENT_SECRET}"
    suggest_db_path: "suggest_purchase.db"
    rule_mode: "report"
```

## Development

```bash
# Run tests
uv run pytest

# Lint and format
uv run ruff check .
uv run ruff format .

# Type check
uv run pyright
```

## Status Workflow

Requests flow through these statuses:
- `new` - Just received
- `in_review` - Being reviewed by staff
- `ordered` - Item ordered
- `declined` - Not purchasing
- `duplicate_or_already_owned` - Already in collection

## License

MIT
