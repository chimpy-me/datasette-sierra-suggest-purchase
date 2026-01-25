#!/bin/bash
# Development startup script for suggest-a-purchase
#
# This script:
# 1. Initializes the database if needed
# 2. Starts the fake Sierra service in the background
# 3. Runs Datasette with the plugin loaded
#
# Usage: ./scripts/dev.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== Suggest-a-Purchase Development Server ==="
echo ""

# Ensure plugin is installed in editable mode
echo "Installing plugin..."
uv pip install -e . -q

# Initialize database if it doesn't exist
if [ ! -f "suggest_purchase.db" ]; then
    echo "Initializing database..."
    uv run python scripts/init_db.py --db suggest_purchase.db
    echo ""
fi

# Check if fake Sierra is already running
FAKE_SIERRA_PID=""
if lsof -i :9009 &>/dev/null; then
    echo "Fake Sierra already running on port 9009"
else
    echo "Starting fake Sierra service on port 9009..."
    uv run python scripts/fake_sierra.py --port 9009 &
    FAKE_SIERRA_PID=$!
    sleep 1
fi

# Set environment for development
export SIERRA_API_BASE="http://127.0.0.1:9009/iii/sierra-api"
export SIERRA_CLIENT_KEY="dev_key"
export SIERRA_CLIENT_SECRET="dev_secret"

# Staff admin account (set password if not already set)
export STAFF_ADMIN_PASSWORD="${STAFF_ADMIN_PASSWORD:-admin}"

echo ""
echo "=== URLs ==="
echo "  Patron UI:    http://127.0.0.1:8001/suggest-purchase"
echo "  Staff login:  http://127.0.0.1:8001/suggest-purchase/staff-login"
echo "  Staff view:   http://127.0.0.1:8001/suggest_purchase/purchase_requests"
echo "  Fake Sierra:  http://127.0.0.1:9009"
echo ""
echo "=== Test Accounts ==="
echo "  Patron:  12345678901234 / 1234  (Test Patron One)"
echo "  Patron:  23456789012345 / 5678  (Test Patron Two)"
echo "  Staff:   admin / ${STAFF_ADMIN_PASSWORD}"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Cleanup function
cleanup() {
    echo ""
    echo "Shutting down..."
    if [ -n "$FAKE_SIERRA_PID" ]; then
        kill $FAKE_SIERRA_PID 2>/dev/null || true
    fi
    exit 0
}

trap cleanup INT TERM

# Run Datasette
uv run datasette suggest_purchase.db \
    --config datasette.yaml \
    --reload \
    --host 127.0.0.1 \
    --port 8001

# Cleanup on exit
cleanup
