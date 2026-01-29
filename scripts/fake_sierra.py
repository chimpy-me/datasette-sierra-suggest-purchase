#!/usr/bin/env python3
"""
Fake Sierra API server for local development and testing.

Implements endpoints for the POC and suggest-a-bot:
- Token authentication (OAuth2 client credentials)
- Patron authentication (barcode + PIN validation)
- Minimal patron info lookup
- Catalog search (M2: bib search by ISBN, title, author)
- Item availability lookup

Run with: python scripts/fake_sierra.py --port 9009
Then set: SIERRA_API_BASE="http://127.0.0.1:9009"
"""

import argparse
import base64
import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# Fake patron database
FAKE_PATRONS = {
    # barcode: {pin, patron_record_id, ptype, home_library, name}
    "12345678901234": {
        "pin": "1234",
        "patron_record_id": 100001,
        "ptype": 3,
        "home_library": "MAIN",
        "name": "Test Patron One",
    },
    "23456789012345": {
        "pin": "5678",
        "patron_record_id": 100002,
        "ptype": 5,
        "home_library": "BRANCH1",
        "name": "Test Patron Two",
    },
    "34567890123456": {
        "pin": "9999",
        "patron_record_id": 100003,
        "ptype": 10,
        "home_library": "BRANCH2",
        "name": "Staff Test User",
    },
}

# Simple token store (in-memory)
VALID_TOKENS: dict[str, float] = {}

# Fake catalog database
# Maps bib_id to bib record data
FAKE_CATALOG = {
    "b1000001": {
        "id": "b1000001",
        "title": "The Women: A Novel",
        "author": "Hannah, Kristin",
        "isbn": ["9780312577230", "9781250178633"],
        "publisher": "St. Martin's Press",
        "publishYear": 2024,
        "materialType": {"code": "a", "value": "Book"},
        "language": {"code": "eng", "name": "English"},
    },
    "b1000002": {
        "id": "b1000002",
        "title": "Handbook of Mathematical Functions",
        "author": "Abramowitz, Milton; Stegun, Irene A.",
        "isbn": ["0306406152", "9780306406157"],
        "publisher": "Dover Publications",
        "publishYear": 1965,
        "materialType": {"code": "a", "value": "Book"},
        "language": {"code": "eng", "name": "English"},
    },
    "b1000003": {
        "id": "b1000003",
        "title": "Project Hail Mary",
        "author": "Weir, Andy",
        "isbn": ["9780593135204", "9780593395561"],
        "publisher": "Ballantine Books",
        "publishYear": 2021,
        "materialType": {"code": "a", "value": "Book"},
        "language": {"code": "eng", "name": "English"},
    },
    "b1000004": {
        "id": "b1000004",
        "title": "The Midnight Library",
        "author": "Haig, Matt",
        "isbn": ["9780525559474"],
        "publisher": "Viking",
        "publishYear": 2020,
        "materialType": {"code": "a", "value": "Book"},
        "language": {"code": "eng", "name": "English"},
    },
}

# Fake items (holdings) for bibs
# Maps bib_id to list of items
FAKE_ITEMS = {
    "b1000001": [
        {
            "id": "i2000001",
            "bibIds": ["b1000001"],
            "location": {"code": "main", "name": "Main Library"},
            "status": {"code": "-", "display": "Available"},
            "callNumber": "PS3608.A713 W66 2024",
        },
        {
            "id": "i2000002",
            "bibIds": ["b1000001"],
            "location": {"code": "branch1", "name": "Branch Library 1"},
            "status": {"code": "c", "display": "Checked out"},
            "dueDate": "2024-02-15",
            "callNumber": "PS3608.A713 W66 2024",
        },
    ],
    "b1000002": [
        {
            "id": "i2000003",
            "bibIds": ["b1000002"],
            "location": {"code": "main", "name": "Main Library"},
            "status": {"code": "-", "display": "Available"},
            "callNumber": "QA47 .A23 1965",
        },
    ],
    "b1000003": [
        {
            "id": "i2000004",
            "bibIds": ["b1000003"],
            "location": {"code": "main", "name": "Main Library"},
            "status": {"code": "-", "display": "Available"},
            "callNumber": "PS3623.E4565 P76 2021",
        },
        {
            "id": "i2000005",
            "bibIds": ["b1000003"],
            "location": {"code": "main", "name": "Main Library"},
            "status": {"code": "-", "display": "Available"},
            "callNumber": "PS3623.E4565 P76 2021",
        },
    ],
    "b1000004": [],  # No items (on order?)
}


class FakeSierraHandler(BaseHTTPRequestHandler):
    """HTTP handler implementing fake Sierra API endpoints."""

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        """Override to add prefix."""
        print(f"[FakeSierra] {args[0]}")

    def send_json(self, data: dict, status: int = 200) -> None:
        """Send a JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def send_error_json(self, status: int, message: str, code: int = 0) -> None:
        """Send a Sierra-style error response."""
        self.send_json(
            {
                "code": code,
                "specificCode": 0,
                "httpStatus": status,
                "name": "Error",
                "description": message,
            },
            status=status,
        )

    def do_POST(self) -> None:
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        # Read body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else ""

        if path == "/iii/sierra-api/v6/token":
            self.handle_token(body)
        elif path == "/iii/sierra-api/v6/patrons/auth":
            self.handle_patron_auth(body)
        else:
            self.send_error_json(404, f"Unknown endpoint: {path}")

    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        query_params = parse_qs(parsed.query)

        # Check for patron lookup: /v6/patrons/{id}
        if path.startswith("/iii/sierra-api/v6/patrons/"):
            patron_id_str = path.split("/")[-1]
            try:
                patron_id = int(patron_id_str)
                self.handle_patron_get(patron_id)
            except ValueError:
                self.send_error_json(400, "Invalid patron ID")
        # Bib search: /v6/bibs
        elif path == "/iii/sierra-api/v6/bibs":
            self.handle_bib_search(query_params)
        # Item lookup: /v6/items
        elif path == "/iii/sierra-api/v6/items":
            self.handle_item_search(query_params)
        else:
            self.send_error_json(404, f"Unknown endpoint: {path}")

    def handle_token(self, body: str) -> None:  # noqa: ARG002
        """Handle OAuth2 token request."""
        # Check Authorization header for client credentials
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            self.send_error_json(401, "Missing or invalid Authorization header")
            return

        # Decode and validate (we accept any credentials for the fake)
        try:
            credentials = base64.b64decode(auth_header[6:]).decode()
            # Validate format but don't check actual credentials for fake server
            _ = credentials.split(":", 1)
        except Exception:
            self.send_error_json(401, "Invalid Authorization header format")
            return

        # Generate a fake token
        token = secrets.token_hex(32)
        VALID_TOKENS[token] = 3600  # expires_in

        self.send_json(
            {
                "access_token": token,
                "token_type": "bearer",
                "expires_in": 3600,
            }
        )

    def handle_patron_auth(self, body: str) -> None:
        """
        Handle patron authentication.

        Sierra's patron auth endpoint accepts barcode + PIN and returns
        the patron record ID on success.
        """
        # Verify bearer token
        if not self.verify_token():
            return

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_error_json(400, "Invalid JSON body")
            return

        barcode = data.get("barcode", "")
        pin = data.get("pin", "")

        if not barcode or not pin:
            self.send_error_json(400, "Missing barcode or pin")
            return

        patron = FAKE_PATRONS.get(barcode)
        if patron is None:
            self.send_error_json(401, "Patron not found", code=107)
            return

        if patron["pin"] != pin:
            self.send_error_json(401, "Invalid PIN", code=108)
            return

        # Success - return patron record ID
        self.send_json(
            {
                "patronId": patron["patron_record_id"],
            }
        )

    def handle_patron_get(self, patron_id: int) -> None:
        """Handle patron lookup by ID."""
        if not self.verify_token():
            return

        # Find patron by record ID
        patron = None
        for p in FAKE_PATRONS.values():
            if p["patron_record_id"] == patron_id:
                patron = p
                break

        if patron is None:
            self.send_error_json(404, "Patron not found", code=107)
            return

        # Return patron info (Sierra-style response)
        self.send_json(
            {
                "id": patron["patron_record_id"],
                "patronType": patron["ptype"],
                "homeLibraryCode": patron["home_library"],
                "names": [patron["name"]],
            }
        )

    def verify_token(self) -> bool:
        """Verify the bearer token in the Authorization header."""
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self.send_error_json(401, "Missing or invalid bearer token")
            return False

        token = auth_header[7:]
        if token not in VALID_TOKENS:
            self.send_error_json(401, "Invalid or expired token")
            return False

        return True

    def handle_bib_search(self, params: dict) -> None:
        """
        Handle bib search requests.

        Sierra supports various search parameters:
        - isbn: Search by ISBN
        - title: Search by title keyword
        - author: Search by author keyword
        - limit: Max results (default 20)
        - offset: Pagination offset
        """
        if not self.verify_token():
            return

        # Get search parameters
        isbn_list = params.get("isbn", [])
        title_list = params.get("title", [])
        author_list = params.get("author", [])
        limit = int(params.get("limit", ["20"])[0])
        offset = int(params.get("offset", ["0"])[0])

        matching_bibs = []

        # ISBN search (exact match on any ISBN in the record)
        if isbn_list:
            search_isbn = isbn_list[0].replace("-", "")
            for bib in FAKE_CATALOG.values():
                bib_isbns = [i.replace("-", "") for i in bib.get("isbn", [])]
                if search_isbn in bib_isbns:
                    matching_bibs.append(bib)

        # Title search (substring match, case-insensitive)
        elif title_list:
            search_title = title_list[0].lower()
            search_author = author_list[0].lower() if author_list else None

            for bib in FAKE_CATALOG.values():
                title_match = search_title in bib.get("title", "").lower()
                if title_match:
                    # If author also specified, require both to match
                    if search_author:
                        author_match = search_author in bib.get("author", "").lower()
                        if author_match:
                            matching_bibs.append(bib)
                    else:
                        matching_bibs.append(bib)

        # Author-only search
        elif author_list:
            search_author = author_list[0].lower()
            for bib in FAKE_CATALOG.values():
                if search_author in bib.get("author", "").lower():
                    matching_bibs.append(bib)

        # Apply pagination
        total = len(matching_bibs)
        matching_bibs = matching_bibs[offset : offset + limit]

        # Format response (Sierra-style)
        self.send_json(
            {
                "total": total,
                "start": offset,
                "entries": [
                    {
                        "id": bib["id"],
                        "title": bib["title"],
                        "author": bib.get("author"),
                        "isbn": bib.get("isbn", []),
                        "publisher": bib.get("publisher"),
                        "publishYear": bib.get("publishYear"),
                        "materialType": bib.get("materialType"),
                        "language": bib.get("language"),
                    }
                    for bib in matching_bibs
                ],
            }
        )

    def handle_item_search(self, params: dict) -> None:
        """
        Handle item search requests.

        Sierra supports:
        - bibIds: Comma-separated list of bib IDs
        - limit: Max results (default 50)
        """
        if not self.verify_token():
            return

        bib_ids_param = params.get("bibIds", [])
        if not bib_ids_param:
            self.send_error_json(400, "bibIds parameter required")
            return

        # Parse comma-separated bib IDs
        bib_ids = bib_ids_param[0].split(",")
        limit = int(params.get("limit", ["50"])[0])

        all_items = []
        for bib_id in bib_ids:
            bib_id = bib_id.strip()
            items = FAKE_ITEMS.get(bib_id, [])
            all_items.extend(items)

        total = len(all_items)
        all_items = all_items[:limit]

        self.send_json(
            {
                "total": total,
                "start": 0,
                "entries": all_items,
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fake Sierra API server")
    parser.add_argument(
        "--port",
        type=int,
        default=9009,
        help="Port to listen on (default: 9009)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), FakeSierraHandler)
    print(f"Fake Sierra API running at http://{args.host}:{args.port}")
    print("Test patrons:")
    for barcode, info in FAKE_PATRONS.items():
        print(f"  Barcode: {barcode}, PIN: {info['pin']}, Name: {info['name']}")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
