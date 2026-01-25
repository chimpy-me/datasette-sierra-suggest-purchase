# Screenshots

This directory contains screenshots for the Executive Summary document.

## Expected Screenshots

| File | Description |
|------|-------------|
| `patron_login.png` | Customer login page with library card form |
| `patron_form.png` | Purchase suggestion submission form |
| `patron_my_requests.png` | My Requests page showing request statuses |
| `staff_login.png` | Staff authentication page |
| `staff_table.png` | Datasette table view of all requests |

## Regenerating Screenshots

1. Start the development server:
   ```bash
   ./scripts/dev.sh
   ```

2. Create sample data for compelling screenshots:
   - Log in as patron (barcode: `12345678901234`, PIN: `1234`)
   - Submit a few purchase requests
   - Log in as staff (admin / your `STAFF_ADMIN_PASSWORD`)
   - Update some request statuses

3. Run the capture script:
   ```bash
   ./scripts/capture_screenshots.sh
   ```

## Manual Capture

For authenticated pages that the script can't capture automatically, you can take manual screenshots:

1. Open the page in your browser
2. Use your browser's screenshot tool or developer tools
3. Save with the expected filename

## Tool: shot-scraper

Screenshots are captured using [shot-scraper](https://github.com/simonw/shot-scraper) by Simon Willison (creator of Datasette).

Install:
```bash
pip install shot-scraper
shot-scraper install
```
