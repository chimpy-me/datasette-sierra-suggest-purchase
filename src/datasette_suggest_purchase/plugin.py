"""
Datasette plugin for patron purchase suggestions with Sierra ILS integration.

POC Implementation - Minimal viable scope for 2-day demo:
- Patron login against Sierra
- Submit request (free-text)
- Confirmation page
- "My requests" page
- Staff update route (minimal)
"""

import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from datasette import Response, hookimpl
from datasette.utils.asgi import Request

# -----------------------------------------------------------------------------
# Plugin Configuration
# -----------------------------------------------------------------------------


def get_plugin_config(datasette) -> dict[str, Any]:
    """Get plugin configuration from datasette.yaml."""
    config = datasette.plugin_config("datasette-suggest-purchase") or {}
    return {
        "sierra_api_base": config.get("sierra_api_base", "http://127.0.0.1:9009/iii/sierra-api"),
        "sierra_client_key": config.get("sierra_client_key", ""),
        "sierra_client_secret": config.get("sierra_client_secret", ""),
        "suggest_db_path": config.get("suggest_db_path", "suggest_purchase.db"),
        "rule_mode": config.get("rule_mode", "report"),
        "rules": config.get("rules", {}),
    }


# -----------------------------------------------------------------------------
# Sierra API Client (minimal for POC)
# -----------------------------------------------------------------------------


class SierraClient:
    """Sierra API client for patron authentication and catalog search."""

    def __init__(self, base_url: str, client_key: str, client_secret: str):
        self.base_url = base_url.rstrip("/")
        self.client_key = client_key
        self.client_secret = client_secret
        self._token: str | None = None

    async def _get_token(self) -> str:
        """Get an OAuth2 access token."""
        if self._token:
            return self._token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v6/token",
                auth=(self.client_key, self.client_secret),
                data={"grant_type": "client_credentials"},
            )
            response.raise_for_status()
            data = response.json()
            self._token = data["access_token"]
            return self._token

    async def authenticate_patron(self, barcode: str, pin: str) -> dict | None:
        """
        Authenticate a patron with barcode and PIN.

        Returns patron info dict on success, None on failure.
        """
        token = await self._get_token()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v6/patrons/auth",
                headers={"Authorization": f"Bearer {token}"},
                json={"barcode": barcode, "pin": pin},
            )

            if response.status_code == 200:
                data = response.json()
                patron_id = data.get("patronId")
                if patron_id:
                    # Optionally fetch more patron details
                    patron_info = await self._get_patron_info(patron_id, token)
                    return patron_info
            return None

    async def _get_patron_info(self, patron_id: int, token: str) -> dict:
        """Fetch patron details by ID."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/v6/patrons/{patron_id}",
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "patron_record_id": data.get("id", patron_id),
                    "ptype": data.get("patronType"),
                    "home_library": data.get("homeLibraryCode"),
                    "name": data.get("names", ["Patron"])[0] if data.get("names") else "Patron",
                }

            # Fall back to minimal info
            return {"patron_record_id": patron_id}

    # -------------------------------------------------------------------------
    # Catalog Search Methods (M2: suggest-a-bot)
    # -------------------------------------------------------------------------

    async def search_by_isbn(self, isbn: str, limit: int = 10) -> dict:
        """
        Search catalog by ISBN.

        Args:
            isbn: ISBN to search (ISBN-10 or ISBN-13, with or without dashes)
            limit: Maximum results to return

        Returns:
            Sierra API response with 'total', 'start', 'entries' keys.
            Returns empty entries on error.
        """
        token = await self._get_token()
        # Normalize ISBN (remove dashes)
        clean_isbn = isbn.replace("-", "")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/v6/bibs",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"isbn": clean_isbn, "limit": limit},
                    timeout=30.0,
                )
                if response.status_code == 200:
                    return response.json()
            except httpx.RequestError as e:
                print(f"[SierraClient] ISBN search error: {e}")

        return {"total": 0, "start": 0, "entries": []}

    async def search_by_title_author(
        self,
        title: str | None = None,
        author: str | None = None,
        limit: int = 10,
    ) -> dict:
        """
        Search catalog by title and/or author keywords.

        Args:
            title: Title keyword search
            author: Author keyword search
            limit: Maximum results to return

        Returns:
            Sierra API response with 'total', 'start', 'entries' keys.
            Returns empty entries on error.
        """
        if not title and not author:
            return {"total": 0, "start": 0, "entries": []}

        token = await self._get_token()
        params: dict[str, Any] = {"limit": limit}
        if title:
            params["title"] = title
        if author:
            params["author"] = author

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/v6/bibs",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                    timeout=30.0,
                )
                if response.status_code == 200:
                    return response.json()
            except httpx.RequestError as e:
                print(f"[SierraClient] Title/author search error: {e}")

        return {"total": 0, "start": 0, "entries": []}

    async def get_item_availability(self, bib_ids: list[str], limit: int = 50) -> dict:
        """
        Get item availability for one or more bib records.

        Args:
            bib_ids: List of bib IDs to check
            limit: Maximum items to return

        Returns:
            Sierra API response with 'total', 'start', 'entries' keys.
            Each entry contains item status, location, call number, etc.
        """
        if not bib_ids:
            return {"total": 0, "start": 0, "entries": []}

        token = await self._get_token()
        bib_ids_param = ",".join(bib_ids)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/v6/items",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"bibIds": bib_ids_param, "limit": limit},
                    timeout=30.0,
                )
                if response.status_code == 200:
                    return response.json()
            except httpx.RequestError as e:
                print(f"[SierraClient] Item availability error: {e}")

        return {"total": 0, "start": 0, "entries": []}


# -----------------------------------------------------------------------------
# Database Helpers
# -----------------------------------------------------------------------------


def get_db_path(datasette) -> Path:
    """Get the path to the suggest_purchase database."""
    config = get_plugin_config(datasette)
    return Path(config["suggest_db_path"])


def ensure_db_exists(db_path: Path) -> None:
    """Ensure the database exists with the correct schema.

    Uses the migration system to create/update the database.
    This is idempotent - safe to call multiple times.
    """
    from datasette_suggest_purchase.migrations import run_migrations

    run_migrations(db_path, verbose=False)


# -----------------------------------------------------------------------------
# Actor Helpers
# -----------------------------------------------------------------------------


def get_patron_actor(request: Request) -> dict | None:
    """Get the patron actor from the request, if authenticated."""
    actor = request.actor
    if actor and actor.get("principal_type") == "patron":
        return actor
    return None


def is_staff(request: Request) -> bool:
    """Check if the current user is staff."""
    actor = request.actor
    return actor is not None and actor.get("principal_type") == "staff"


# -----------------------------------------------------------------------------
# Template Rendering Helper
# -----------------------------------------------------------------------------


async def render_template(datasette, request, template_name: str, context: dict) -> Response:
    """Render a template with the given context."""
    return Response.html(
        await datasette.render_template(
            template_name,
            {**context, "request": request},
            request=request,
        )
    )


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


async def suggest_purchase_index(request: Request, datasette) -> Response:
    """
    Main suggest-purchase page.

    If not authenticated: show login form.
    If authenticated: show submission form.
    """
    patron = get_patron_actor(request)

    if patron:
        # Show submission form
        return await render_template(
            datasette,
            request,
            "suggest_purchase_form.html",
            {"patron": patron},
        )
    else:
        # Show login form
        error = request.args.get("error", "")
        return await render_template(
            datasette,
            request,
            "suggest_purchase_login.html",
            {"error": error},
        )


async def suggest_purchase_login(request: Request, datasette) -> Response:
    """Handle patron login POST."""
    if request.method != "POST":
        return Response.redirect("/suggest-purchase")

    # Get form data
    formdata = await request.post_vars()
    barcode = formdata.get("barcode", "").strip()
    pin = formdata.get("pin", "").strip()

    if not barcode or not pin:
        error_msg = "Please enter your library card number and PIN."
        return Response.redirect("/suggest-purchase?" + urlencode({"error": error_msg}))

    # Authenticate with Sierra
    config = get_plugin_config(datasette)
    client = SierraClient(
        config["sierra_api_base"],
        config["sierra_client_key"],
        config["sierra_client_secret"],
    )

    try:
        patron_info = await client.authenticate_patron(barcode, pin)
    except Exception as e:
        # Log the error but show a generic message
        print(f"[suggest-purchase] Sierra auth error: {e}")
        error_msg = "Unable to connect to library system. Please try again."
        return Response.redirect("/suggest-purchase?" + urlencode({"error": error_msg}))

    if patron_info is None:
        error_msg = "Invalid library card number or PIN."
        return Response.redirect("/suggest-purchase?" + urlencode({"error": error_msg}))

    # Build patron actor
    patron_record_id = patron_info["patron_record_id"]
    actor = {
        "id": f"patron:{patron_record_id}",
        "principal_type": "patron",
        "principal_id": str(patron_record_id),
        "display": patron_info.get("name", "Patron"),
        "sierra": {
            "patron_record_id": patron_record_id,
            "ptype": patron_info.get("ptype"),
            "home_library": patron_info.get("home_library"),
        },
    }

    # Set the actor cookie and redirect
    response = Response.redirect("/suggest-purchase")
    response.set_cookie(
        "ds_actor",
        datasette.sign({"a": actor}, "actor"),
        httponly=True,
        samesite="lax",
        # secure=True,  # Enable in production with HTTPS
        max_age=3600 * 24,  # 24 hours
    )

    return response


async def suggest_purchase_logout(request: Request, datasette) -> Response:
    """Handle patron logout."""
    response = Response.redirect("/suggest-purchase")
    response.set_cookie("ds_actor", "", max_age=0)
    return response


async def suggest_purchase_submit(request: Request, datasette) -> Response:
    """Handle purchase suggestion submission."""
    if request.method != "POST":
        return Response.redirect("/suggest-purchase")

    patron = get_patron_actor(request)
    if not patron:
        return Response.redirect("/suggest-purchase")

    # Get form data
    formdata = await request.post_vars()
    raw_query = formdata.get("query", "").strip()
    format_preference = formdata.get("format", "").strip() or None
    patron_notes = formdata.get("notes", "").strip() or None

    if not raw_query:
        error_msg = "Please enter what you would like us to consider purchasing."
        return await render_template(
            datasette,
            request,
            "suggest_purchase_form.html",
            {"patron": patron, "error": error_msg},
        )

    # Create the request record
    request_id = secrets.token_hex(16)
    created_ts = datetime.now(UTC).isoformat()
    patron_record_id = patron["sierra"]["patron_record_id"]

    db_path = get_db_path(datasette)
    ensure_db_exists(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO purchase_requests
                (request_id, created_ts, patron_record_id, raw_query,
                 format_preference, patron_notes, status)
            VALUES (?, ?, ?, ?, ?, ?, 'new')
            """,
            (request_id, created_ts, patron_record_id, raw_query, format_preference, patron_notes),
        )
        conn.commit()
    finally:
        conn.close()

    return Response.redirect(f"/suggest-purchase/confirmation?request_id={request_id}")


async def suggest_purchase_confirmation(request: Request, datasette) -> Response:
    """Show submission confirmation."""
    patron = get_patron_actor(request)
    if not patron:
        return Response.redirect("/suggest-purchase")

    request_id = request.args.get("request_id", "")

    db_path = get_db_path(datasette)
    if not db_path.exists():
        return Response.redirect("/suggest-purchase")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT raw_query, format_preference, created_ts
            FROM purchase_requests WHERE request_id = ?
            """,
            (request_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return Response.redirect("/suggest-purchase")

    return await render_template(
        datasette,
        request,
        "suggest_purchase_confirmation.html",
        {
            "patron": patron,
            "request_id": request_id,
            "raw_query": row[0],
            "format_preference": row[1],
            "created_ts": row[2],
        },
    )


async def suggest_purchase_my_requests(request: Request, datasette) -> Response:
    """Show patron's own requests."""
    patron = get_patron_actor(request)
    if not patron:
        return Response.redirect("/suggest-purchase")

    patron_record_id = patron["sierra"]["patron_record_id"]

    db_path = get_db_path(datasette)
    if not db_path.exists():
        requests_list = []
    else:
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                """
                SELECT request_id, raw_query, format_preference, status, created_ts
                FROM purchase_requests
                WHERE patron_record_id = ?
                ORDER BY created_ts DESC
                """,
                (patron_record_id,),
            )
            requests_list = [
                {
                    "request_id": row[0],
                    "raw_query": row[1],
                    "format_preference": row[2],
                    "status": row[3],
                    "created_ts": row[4],
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    return await render_template(
        datasette,
        request,
        "suggest_purchase_my_requests.html",
        {"patron": patron, "requests": requests_list},
    )


async def staff_login_page(request: Request, datasette) -> Response:
    """Show staff login form or handle login POST."""
    if request.method == "POST":
        return await staff_login_submit(request, datasette)

    # GET - show login form
    error = request.args.get("error", "")
    return await render_template(
        datasette,
        request,
        "suggest_purchase_staff_login.html",
        {"error": error},
    )


async def staff_login_submit(request: Request, datasette) -> Response:
    """Handle staff login POST."""
    from datasette_suggest_purchase.staff_auth import authenticate_staff

    formdata = await request.post_vars()
    username = formdata.get("username", "").strip()
    password = formdata.get("password", "").strip()

    if not username or not password:
        error_msg = "Please enter your username and password."
        return Response.redirect("/suggest-purchase/staff-login?" + urlencode({"error": error_msg}))

    db_path = get_db_path(datasette)
    ensure_db_exists(db_path)

    account = authenticate_staff(db_path, username, password)

    if account is None:
        error_msg = "Invalid username or password."
        return Response.redirect("/suggest-purchase/staff-login?" + urlencode({"error": error_msg}))

    # Build staff actor
    actor = {
        "id": f"staff:{username}",
        "principal_type": "staff",
        "principal_id": username,
        "display": account.get("display_name") or username,
    }

    # Set the actor cookie and redirect to staff view
    response = Response.redirect("/suggest_purchase/purchase_requests")
    response.set_cookie(
        "ds_actor",
        datasette.sign({"a": actor}, "actor"),
        httponly=True,
        samesite="lax",
        # secure=True,  # Enable in production with HTTPS
        max_age=3600 * 8,  # 8 hours for staff sessions
    )

    return response


async def staff_request_update(request: Request, datasette) -> Response:
    """Staff route to update a request's status and notes."""
    # Check staff authorization - POC uses simple principal_type check
    if not is_staff(request):
        return Response.text("Unauthorized", status=403)

    if request.method != "POST":
        return Response.text("Method not allowed", status=405)

    # Extract request_id from URL path
    path_parts = request.url_vars.get("request_id")
    if not path_parts:
        return Response.text("Missing request_id", status=400)

    request_id = path_parts

    formdata = await request.post_vars()
    new_status = formdata.get("status", "").strip()
    staff_notes = formdata.get("staff_notes", "").strip() or None

    valid_statuses = ["new", "in_review", "ordered", "declined", "duplicate_or_already_owned"]
    if new_status and new_status not in valid_statuses:
        return Response.text(f"Invalid status. Must be one of: {valid_statuses}", status=400)

    db_path = get_db_path(datasette)
    if not db_path.exists():
        return Response.text("Database not found", status=404)

    updated_ts = datetime.now(UTC).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        if new_status and staff_notes is not None:
            conn.execute(
                """UPDATE purchase_requests
                SET status = ?, staff_notes = ?, updated_ts = ? WHERE request_id = ?""",
                (new_status, staff_notes, updated_ts, request_id),
            )
        elif new_status:
            conn.execute(
                "UPDATE purchase_requests SET status = ?, updated_ts = ? WHERE request_id = ?",
                (new_status, updated_ts, request_id),
            )
        elif staff_notes is not None:
            conn.execute(
                "UPDATE purchase_requests SET staff_notes = ?, updated_ts = ? WHERE request_id = ?",
                (staff_notes, updated_ts, request_id),
            )
        conn.commit()
    finally:
        conn.close()

    # Redirect back to the Datasette table view
    return Response.redirect(f"/suggest_purchase/purchase_requests/{request_id}")


# -----------------------------------------------------------------------------
# Datasette Hooks
# -----------------------------------------------------------------------------


@hookimpl
def register_routes():
    """Register plugin routes with Datasette."""
    return [
        # Patron routes
        (r"^/suggest-purchase$", suggest_purchase_index),
        (r"^/suggest-purchase/login$", suggest_purchase_login),
        (r"^/suggest-purchase/logout$", suggest_purchase_logout),
        (r"^/suggest-purchase/submit$", suggest_purchase_submit),
        (r"^/suggest-purchase/confirmation$", suggest_purchase_confirmation),
        (r"^/suggest-purchase/my-requests$", suggest_purchase_my_requests),
        # Staff routes
        (r"^/suggest-purchase/staff-login$", staff_login_page),
        (r"^/-/suggest-purchase/request/(?P<request_id>[^/]+)/update$", staff_request_update),
    ]


@hookimpl
def extra_template_vars(datasette):
    """Provide extra template variables."""
    return {
        "suggest_purchase_version": "0.1.0",
    }


# Register templates directory
TEMPLATES_DIR = Path(__file__).parent / "templates"


@hookimpl
def prepare_jinja2_environment(env, datasette):
    """Add the plugin's templates directory to the Jinja2 environment."""
    from jinja2 import ChoiceLoader, FileSystemLoader

    # Prepend our templates to the loader
    if hasattr(env, "loader"):
        env.loader = ChoiceLoader([FileSystemLoader(str(TEMPLATES_DIR)), env.loader])


@hookimpl
def skip_csrf(datasette, scope):
    """
    Skip CSRF for specific routes with deliberate reasons.

    - Login routes: No prior authenticated page to obtain a token
    - Staff API routes: Internal API-style calls, protected by auth check
    """
    path = scope.get("path", "")
    # Patron login: no prior authenticated page to get token
    if path == "/suggest-purchase/login":
        return True
    # Staff login: no prior authenticated page to get token
    if path == "/suggest-purchase/staff-login":
        return True
    # Staff API routes: internal API-style calls, protected by auth check
    if path.startswith("/-/suggest-purchase/"):
        return True
    return None


@hookimpl
def startup(datasette):
    """
    Run on Datasette startup.

    Syncs staff admin account from environment variables if configured.
    """
    from datasette_suggest_purchase.staff_auth import sync_admin_from_env

    db_path = get_db_path(datasette)
    ensure_db_exists(db_path)
    sync_admin_from_env(db_path, verbose=True)


@hookimpl
def permission_allowed(datasette, actor, action):
    """
    Handle permission checks for custom plugin actions.

    Note: Built-in Datasette actions (view-table, view-database, execute-sql)
    are now handled by YAML config in datasette.yaml under 'databases'.
    """
    if not actor:
        return None

    principal_type = actor.get("principal_type")

    # Patron permissions
    if action == "suggest_purchase_submit":
        return principal_type == "patron"

    if action == "suggest_purchase_view_own":
        return principal_type == "patron"

    # Staff permissions
    if action in ("suggest_purchase_review", "suggest_purchase_update", "suggest_purchase_export"):
        return principal_type == "staff"

    return None
