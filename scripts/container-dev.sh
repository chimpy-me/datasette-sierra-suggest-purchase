#!/bin/bash
# Container development script (podman-compose)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== Suggest-a-Purchase Container Dev ==="
echo ""

# Handle arguments
case "${1:-up}" in
  build)
    echo "Building containers..."
    podman-compose build
    ;;
  down)
    echo "Stopping containers..."
    podman-compose down
    exit 0
    ;;
  logs)
    podman-compose logs -f
    exit 0
    ;;
  *)
    # Build if needed, then start
    if [[ "$1" == "--build" ]]; then
      podman-compose build
    fi
    ;;
esac

# Initialize database if it doesn't exist
if [ ! -f "suggest_purchase.db" ]; then
    echo "Initializing database..."
    uv run python scripts/init_db.py --db suggest_purchase.db
    echo ""
fi

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
echo "Commands: ./scripts/container-dev.sh [build|down|logs]"
echo "Press Ctrl+C to stop"
echo ""

podman-compose up
