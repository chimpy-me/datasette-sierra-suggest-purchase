"""
Data models and database operations for suggest-a-bot.
"""

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path


class BotStatus(str, Enum):
    """Processing status for a purchase request."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    SKIPPED = "skipped"


class RunStatus(str, Enum):
    """Status of a bot run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CatalogMatch(str, Enum):
    """Result of catalog lookup."""

    EXACT = "exact"
    PARTIAL = "partial"
    NONE = "none"


class EventType(str, Enum):
    """Types of events in the audit trail."""

    # Patron/staff events
    SUBMITTED = "submitted"
    STATUS_CHANGED = "status_changed"
    NOTE_ADDED = "note_added"

    # Bot events
    BOT_STARTED = "bot_started"
    BOT_EVIDENCE_EXTRACTED = "bot_evidence_extracted"
    BOT_CATALOG_CHECKED = "bot_catalog_checked"
    BOT_OPENLIBRARY_CHECKED = "bot_openlibrary_checked"
    BOT_CONSORTIUM_CHECKED = "bot_consortium_checked"
    BOT_REFINED = "bot_refined"
    BOT_ASSESSED = "bot_assessed"
    BOT_ACTION_TAKEN = "bot_action_taken"
    BOT_COMPLETED = "bot_completed"
    BOT_ERROR = "bot_error"


@dataclass
class PurchaseRequest:
    """A purchase suggestion from a patron."""

    request_id: str
    created_ts: str
    patron_record_id: int
    raw_query: str
    status: str
    format_preference: str | None = None
    patron_notes: str | None = None
    staff_notes: str | None = None
    updated_ts: str | None = None

    # Bot processing fields
    bot_status: str = "pending"
    bot_processed_ts: str | None = None
    bot_error: str | None = None

    # Catalog lookup
    catalog_match: str | None = None
    catalog_holdings_json: str | None = None
    catalog_checked_ts: str | None = None

    # Consortium check
    consortium_available: int | None = None
    consortium_sources_json: str | None = None
    consortium_checked_ts: str | None = None

    # Input refinement
    refined_title: str | None = None
    refined_author: str | None = None
    refined_isbn: str | None = None
    authority_source: str | None = None
    refinement_confidence: float | None = None

    # Bot assessment
    bot_assessment_json: str | None = None
    bot_notes: str | None = None

    # Automatic actions
    bot_action: str | None = None
    bot_action_ts: str | None = None

    # Evidence packet (Milestone 1)
    evidence_packet_json: str | None = None
    evidence_extracted_ts: str | None = None

    # Open Library enrichment (Milestone 3)
    openlibrary_found: int | None = None
    openlibrary_enrichment_json: str | None = None
    openlibrary_checked_ts: str | None = None

    @property
    def evidence_packet(self) -> dict | None:
        """Parse evidence_packet_json."""
        if self.evidence_packet_json:
            return json.loads(self.evidence_packet_json)
        return None

    @property
    def catalog_holdings(self) -> list[dict] | None:
        """Parse catalog_holdings_json."""
        if self.catalog_holdings_json:
            return json.loads(self.catalog_holdings_json)
        return None

    @property
    def consortium_sources(self) -> list[dict] | None:
        """Parse consortium_sources_json."""
        if self.consortium_sources_json:
            return json.loads(self.consortium_sources_json)
        return None

    @property
    def bot_assessment(self) -> dict | None:
        """Parse bot_assessment_json."""
        if self.bot_assessment_json:
            return json.loads(self.bot_assessment_json)
        return None

    @property
    def openlibrary_enrichment(self) -> dict | None:
        """Parse openlibrary_enrichment_json."""
        if self.openlibrary_enrichment_json:
            return json.loads(self.openlibrary_enrichment_json)
        return None


@dataclass
class BotRun:
    """A single execution of the suggest-a-bot processor."""

    run_id: str
    started_ts: str
    status: str = "running"
    completed_ts: str | None = None
    requests_processed: int = 0
    requests_errored: int = 0
    config_snapshot_json: str | None = None
    error_message: str | None = None


@dataclass
class RequestEvent:
    """An audit log entry for a purchase request."""

    event_id: str
    request_id: str
    ts: str
    actor_id: str
    event_type: str
    payload_json: str | None = None

    @property
    def payload(self) -> dict | None:
        """Parse payload_json."""
        if self.payload_json:
            return json.loads(self.payload_json)
        return None


class BotDatabase:
    """Database operations for suggest-a-bot."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_pending_requests(self, limit: int = 50) -> list[PurchaseRequest]:
        """Get requests that need bot processing."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM purchase_requests
                WHERE bot_status = 'pending'
                ORDER BY created_ts ASC
                LIMIT ?
                """,
                (limit,),
            )
            return [PurchaseRequest(**dict(row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_request(self, request_id: str) -> PurchaseRequest | None:
        """Get a single request by ID."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT * FROM purchase_requests WHERE request_id = ?",
                (request_id,),
            )
            row = cursor.fetchone()
            return PurchaseRequest(**dict(row)) if row else None
        finally:
            conn.close()

    def update_request(self, request_id: str, **fields) -> None:
        """Update fields on a purchase request."""
        if not fields:
            return

        conn = self._connect()
        try:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [request_id]
            conn.execute(
                f"UPDATE purchase_requests SET {set_clause} WHERE request_id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()

    def mark_processing(self, request_id: str) -> None:
        """Mark a request as currently being processed."""
        self.update_request(request_id, bot_status=BotStatus.PROCESSING.value)

    def mark_completed(self, request_id: str) -> None:
        """Mark a request as successfully processed."""
        now = datetime.now(UTC).isoformat()
        self.update_request(
            request_id,
            bot_status=BotStatus.COMPLETED.value,
            bot_processed_ts=now,
        )

    def mark_error(self, request_id: str, error: str) -> None:
        """Mark a request as failed with an error."""
        now = datetime.now(UTC).isoformat()
        self.update_request(
            request_id,
            bot_status=BotStatus.ERROR.value,
            bot_processed_ts=now,
            bot_error=error,
        )

    def save_catalog_result(
        self,
        request_id: str,
        match: CatalogMatch,
        holdings: list[dict] | None = None,
    ) -> None:
        """Save catalog lookup results."""
        now = datetime.now(UTC).isoformat()
        self.update_request(
            request_id,
            catalog_match=match.value,
            catalog_holdings_json=json.dumps(holdings) if holdings else None,
            catalog_checked_ts=now,
        )

    def save_consortium_result(
        self,
        request_id: str,
        available: bool,
        sources: list[dict] | None = None,
    ) -> None:
        """Save consortium check results."""
        now = datetime.now(UTC).isoformat()
        self.update_request(
            request_id,
            consortium_available=1 if available else 0,
            consortium_sources_json=json.dumps(sources) if sources else None,
            consortium_checked_ts=now,
        )

    def save_refinement(
        self,
        request_id: str,
        title: str | None = None,
        author: str | None = None,
        isbn: str | None = None,
        source: str | None = None,
        confidence: float | None = None,
    ) -> None:
        """Save input refinement results."""
        self.update_request(
            request_id,
            refined_title=title,
            refined_author=author,
            refined_isbn=isbn,
            authority_source=source,
            refinement_confidence=confidence,
        )

    def save_assessment(
        self,
        request_id: str,
        assessment: dict,
        notes: str | None = None,
    ) -> None:
        """Save bot assessment results."""
        self.update_request(
            request_id,
            bot_assessment_json=json.dumps(assessment),
            bot_notes=notes,
        )

    def save_evidence_packet(
        self,
        request_id: str,
        evidence_packet: dict,
    ) -> None:
        """Save evidence packet for a request."""
        now = datetime.now(UTC).isoformat()
        self.update_request(
            request_id,
            evidence_packet_json=json.dumps(evidence_packet),
            evidence_extracted_ts=now,
        )

    def save_openlibrary_result(
        self,
        request_id: str,
        found: bool,
        enrichment: dict | None = None,
    ) -> None:
        """Save Open Library enrichment results."""
        now = datetime.now(UTC).isoformat()
        self.update_request(
            request_id,
            openlibrary_found=1 if found else 0,
            openlibrary_enrichment_json=json.dumps(enrichment) if enrichment else None,
            openlibrary_checked_ts=now,
        )

    # -------------------------------------------------------------------------
    # Bot runs
    # -------------------------------------------------------------------------

    def create_run(self, config: dict | None = None) -> BotRun:
        """Create a new bot run record."""
        run = BotRun(
            run_id=secrets.token_hex(16),
            started_ts=datetime.now(UTC).isoformat(),
            config_snapshot_json=json.dumps(config) if config else None,
        )

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO bot_runs (run_id, started_ts, status, config_snapshot_json)
                VALUES (?, ?, ?, ?)
                """,
                (run.run_id, run.started_ts, run.status, run.config_snapshot_json),
            )
            conn.commit()
        finally:
            conn.close()

        return run

    def complete_run(
        self,
        run_id: str,
        processed: int,
        errored: int,
        status: RunStatus = RunStatus.COMPLETED,
        error_message: str | None = None,
    ) -> None:
        """Mark a bot run as complete."""
        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE bot_runs SET
                    completed_ts = ?,
                    status = ?,
                    requests_processed = ?,
                    requests_errored = ?,
                    error_message = ?
                WHERE run_id = ?
                """,
                (now, status.value, processed, errored, error_message, run_id),
            )
            conn.commit()
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Events
    # -------------------------------------------------------------------------

    def add_event(
        self,
        request_id: str,
        event_type: EventType,
        actor_id: str = "bot:suggest-a-bot",
        payload: dict | None = None,
    ) -> str:
        """Add an event to the audit trail."""
        event_id = secrets.token_hex(16)
        now = datetime.now(UTC).isoformat()

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO request_events
                    (event_id, request_id, ts, actor_id, event_type, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    request_id,
                    now,
                    actor_id,
                    event_type.value,
                    json.dumps(payload) if payload else None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return event_id

    def get_events(self, request_id: str) -> list[RequestEvent]:
        """Get all events for a request."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT * FROM request_events WHERE request_id = ? ORDER BY ts ASC",
                (request_id,),
            )
            return [RequestEvent(**dict(row)) for row in cursor.fetchall()]
        finally:
            conn.close()
