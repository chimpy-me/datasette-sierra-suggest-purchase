#!/usr/bin/env bash
#
# Capture screenshots for the Executive Summary document
#
# Prerequisites:
#   pip install shot-scraper
#   shot-scraper install
#
# Usage:
#   1. Start the dev server: ./scripts/dev.sh
#   2. (Optional) Create sample data for better screenshots
#   3. Run this script: ./scripts/capture_screenshots.sh
#
# The script captures:
#   - Patron login page
#   - Patron submission form (after login)
#   - My Requests page
#   - Staff login page
#   - Staff table view

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SCREENSHOT_DIR="$PROJECT_ROOT/docs/screenshots"

BASE_URL="${BASE_URL:-http://127.0.0.1:8001}"
TEST_BARCODE="${TEST_BARCODE:-12345678901234}"
TEST_PIN="${TEST_PIN:-1234}"
STAFF_PASSWORD="${STAFF_ADMIN_PASSWORD:-adminpassword}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prereqs() {
    if ! command -v shot-scraper &> /dev/null; then
        error "shot-scraper not found. Install with: pip install shot-scraper"
        error "Then run: shot-scraper install"
        exit 1
    fi

    # Check if server is running
    if ! curl -s "$BASE_URL" > /dev/null 2>&1; then
        error "Server not running at $BASE_URL"
        error "Start with: ./scripts/dev.sh"
        exit 1
    fi

    info "Prerequisites OK"
}

# Ensure screenshot directory exists
setup_dirs() {
    mkdir -p "$SCREENSHOT_DIR"
    info "Screenshot directory: $SCREENSHOT_DIR"
}

# Capture unauthenticated pages
capture_public_pages() {
    info "Capturing public pages..."

    # Patron login page
    info "  - Patron login page"
    shot-scraper "$BASE_URL/suggest-purchase" \
        -o "$SCREENSHOT_DIR/patron_login.png" \
        --width 1200 --height 800 \
        --wait 1000 \
        --retina

    # Staff login page
    info "  - Staff login page"
    shot-scraper "$BASE_URL/suggest-purchase/staff-login" \
        -o "$SCREENSHOT_DIR/staff_login.png" \
        --width 1200 --height 600 \
        --wait 1000 \
        --retina
}

# Capture patron authenticated pages
capture_patron_pages() {
    info "Capturing patron pages (with authentication)..."

    # Login and capture submission form
    info "  - Patron submission form"
    shot-scraper "$BASE_URL/suggest-purchase" \
        -o "$SCREENSHOT_DIR/patron_form.png" \
        --width 1200 --height 900 \
        --wait 1000 \
        --retina \
        --javascript "
            // Fill and submit login form
            const barcodeInput = document.querySelector('input[name=\"barcode\"]');
            const pinInput = document.querySelector('input[name=\"pin\"]');
            if (barcodeInput && pinInput) {
                barcodeInput.value = '$TEST_BARCODE';
                pinInput.value = '$TEST_PIN';
                document.querySelector('form').submit();
            }
        " \
        --wait-for "input[name='raw_query']" 2>/dev/null || {
            warn "  Could not capture patron form (login may have failed)"
        }

    # My Requests page
    info "  - My Requests page"
    shot-scraper "$BASE_URL/suggest-purchase/my-requests" \
        -o "$SCREENSHOT_DIR/patron_my_requests.png" \
        --width 1200 --height 800 \
        --wait 1000 \
        --retina \
        --javascript "
            // Login first via form submission
            fetch('$BASE_URL/suggest-purchase/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'barcode=$TEST_BARCODE&pin=$TEST_PIN',
                credentials: 'include'
            });
        " 2>/dev/null || {
            warn "  Could not capture my-requests (requires active session)"
        }
}

# Capture staff authenticated pages
capture_staff_pages() {
    info "Capturing staff pages (with authentication)..."

    # Staff table view - this requires staff cookie
    info "  - Staff table view"
    shot-scraper "$BASE_URL/suggest_purchase/purchase_requests" \
        -o "$SCREENSHOT_DIR/staff_table.png" \
        --width 1400 --height 900 \
        --wait 1500 \
        --retina \
        --javascript "
            // Attempt to authenticate via staff login
            console.log('Capturing staff table view');
        " 2>/dev/null || {
            warn "  Could not capture staff table (may require authentication)"
        }
}

# Create sample data for better screenshots
create_sample_data() {
    info "Tip: For better screenshots, create sample data first:"
    echo ""
    echo "  1. Log in as patron (barcode: 12345678901234, PIN: 1234)"
    echo "  2. Submit a few purchase requests with different content:"
    echo "     - 'Project Hail Mary by Andy Weir - audiobook please'"
    echo "     - 'ISBN 978-0-06-231609-7 The Alchemist'"
    echo "     - 'Something about learning Python for beginners'"
    echo ""
    echo "  3. Log in as staff (admin / \$STAFF_ADMIN_PASSWORD)"
    echo "  4. Update some request statuses to show variety"
    echo ""
}

# Alternative: use playwright directly for authenticated pages
capture_with_playwright() {
    info "For authenticated pages, you can also use Playwright directly:"
    echo ""
    echo "  pip install playwright"
    echo "  playwright install chromium"
    echo ""
    echo "  Then create a Python script for more complex scenarios."
}

main() {
    echo "========================================"
    echo "Suggest a Purchase Screenshot Capture"
    echo "========================================"
    echo ""

    check_prereqs
    setup_dirs

    echo ""
    capture_public_pages

    echo ""
    capture_patron_pages

    echo ""
    capture_staff_pages

    echo ""
    echo "========================================"
    info "Screenshot capture complete!"
    echo ""
    echo "Screenshots saved to: $SCREENSHOT_DIR"
    ls -la "$SCREENSHOT_DIR"/*.png 2>/dev/null || warn "No screenshots captured"
    echo ""

    create_sample_data
}

main "$@"
