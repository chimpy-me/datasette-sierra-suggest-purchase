"""
Processing pipeline for suggest-a-bot.

Each stage in the pipeline enriches the purchase request with additional
information that helps staff make decisions.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .catalog import CatalogSearcher, determine_match_type
from .config import BotConfig
from .evidence import EvidencePacket, EvidencePacketBuilder
from .models import (
    BotDatabase,
    CatalogMatch,
    EventType,
    PurchaseRequest,
)
from .openlibrary import OpenLibraryClient, enrich_from_openlibrary, scrub_pii

logger = logging.getLogger(__name__)


@dataclass
class StageResult:
    """Result from a pipeline stage."""

    success: bool
    message: str | None = None
    data: dict[str, Any] | None = None


class PipelineStage(ABC):
    """Base class for pipeline stages."""

    name: str = "base"

    def __init__(self, config: BotConfig, db: BotDatabase):
        self.config = config
        self.db = db

    @abstractmethod
    async def process(self, request: PurchaseRequest) -> StageResult:
        """Process a request through this stage."""
        pass

    def is_enabled(self) -> bool:
        """Check if this stage is enabled in config."""
        return True


class EvidenceExtractionStage(PipelineStage):
    """Stage 0: Extract and structure evidence from patron input.

    This stage is always enabled as it provides the foundation for
    all other processing stages. It extracts identifiers (ISBN, ISSN,
    DOI, URLs) and structures the input into an evidence packet.
    """

    name = "evidence_extraction"

    def is_enabled(self) -> bool:
        # Always enabled - foundation for all other stages
        return True

    async def process(self, request: PurchaseRequest) -> StageResult:
        """
        Build evidence packet from patron input.

        Extracts identifiers and metadata, saves to database.
        """
        logger.info(f"Evidence extraction for request {request.request_id}")

        try:
            # Build evidence packet from request fields
            builder = EvidencePacketBuilder(
                omni_input=request.raw_query,
                format_preference=request.format_preference,
                patron_notes=request.patron_notes,
            )
            packet = builder.build()
            packet_dict = packet.to_dict()

            # Save to database
            self.db.save_evidence_packet(request.request_id, packet_dict)

            # Build summary for event log
            summary = {
                "isbn_count": len(packet.identifiers.isbn),
                "issn_count": len(packet.identifiers.issn),
                "doi_count": len(packet.identifiers.doi),
                "url_count": len(packet.identifiers.urls),
                "valid_isbn_present": packet.quality.signals.valid_isbn_present,
                "title_like_text_present": packet.quality.signals.title_like_text_present,
            }

            # Log event
            self.db.add_event(
                request.request_id,
                EventType.BOT_EVIDENCE_EXTRACTED,
                payload=summary,
            )

            logger.info(
                f"Evidence extracted for {request.request_id}: "
                f"{summary['isbn_count']} ISBNs, "
                f"{summary['url_count']} URLs"
            )

            return StageResult(
                success=True,
                message="Evidence packet created",
                data=packet_dict,
            )

        except Exception as e:
            logger.exception(f"Error extracting evidence for {request.request_id}")
            return StageResult(
                success=False,
                message=f"Evidence extraction failed: {e}",
            )


class CatalogLookupStage(PipelineStage):
    """Stage 1: Check if item exists in our catalog.

    Uses evidence packet identifiers to search Sierra catalog:
    1. ISBN search (highest confidence)
    2. Title + Author search (medium confidence)
    3. Title only search (lowest confidence)

    Saves results as CandidateSets artifact and determines match type.
    """

    name = "catalog_lookup"

    def __init__(self, config: BotConfig, db: BotDatabase, sierra_client=None):
        super().__init__(config, db)
        self._sierra_client = sierra_client

    def is_enabled(self) -> bool:
        return self.config.stages.catalog_lookup

    def _get_sierra_client(self):
        """Get or create Sierra client."""
        if self._sierra_client is not None:
            return self._sierra_client

        # Import here to avoid circular dependency
        from datasette_suggest_purchase.plugin import SierraClient

        return SierraClient(
            base_url=self.config.sierra.api_base,
            client_key=self.config.sierra.client_key,
            client_secret=self.config.sierra.client_secret,
        )

    async def process(self, request: PurchaseRequest) -> StageResult:
        """
        Search the Sierra catalog for matching items.

        Uses evidence packet from the previous stage to search.
        """
        logger.info(f"Catalog lookup for request {request.request_id}")

        # Get evidence packet
        evidence_dict = request.evidence_packet
        if not evidence_dict:
            logger.warning(
                f"No evidence packet for {request.request_id}, skipping catalog lookup"
            )
            return StageResult(
                success=True,
                message="Skipped: no evidence packet available",
                data={"match": "none", "skipped": True},
            )

        try:
            # Parse evidence packet
            evidence = EvidencePacket.from_dict(evidence_dict)

            # Check if we have any search criteria
            has_isbn = bool(evidence.identifiers.isbn)
            has_title = bool(evidence.extracted.title_guess)

            if not has_isbn and not has_title:
                logger.info(
                    f"No searchable identifiers for {request.request_id}, skipping"
                )
                # Still log the event
                self.db.add_event(
                    request.request_id,
                    EventType.BOT_CATALOG_CHECKED,
                    payload={
                        "match": "none",
                        "skipped": True,
                        "reason": "no_search_criteria",
                    },
                )
                return StageResult(
                    success=True,
                    message="Skipped: no searchable identifiers",
                    data={"match": "none", "skipped": True},
                )

            # Execute search
            sierra_client = self._get_sierra_client()
            searcher = CatalogSearcher(sierra_client)
            candidate_sets = await searcher.search(evidence)

            # Determine match type
            match_str = determine_match_type(candidate_sets, evidence)
            match = CatalogMatch(match_str)

            # Build holdings summary for database storage
            all_candidates = candidate_sets.get_all_candidates()
            holdings = [c.to_dict() for c in all_candidates]

            # Save results
            self.db.save_catalog_result(request.request_id, match, holdings)

            # Also save the full candidate sets artifact
            self.db.update_request(
                request.request_id,
                catalog_holdings_json=candidate_sets.to_json(),
            )

            # Build event summary
            event_payload = {
                "match": match.value,
                "candidates_found": len(all_candidates),
                "search_strategy": self._describe_search_strategy(evidence),
            }

            # Add first match info if available
            if all_candidates:
                first = all_candidates[0]
                event_payload["first_match"] = {
                    "title": first.title,
                    "bib_id": first.source_record_ref.get("bib_id"),
                    "available": first.source_record_ref.get("availability") == "available",
                }

            # Log event
            self.db.add_event(
                request.request_id,
                EventType.BOT_CATALOG_CHECKED,
                payload=event_payload,
            )

            logger.info(
                f"Catalog lookup for {request.request_id}: {match.value}, "
                f"{len(all_candidates)} candidates found"
            )

            return StageResult(
                success=True,
                message=f"Catalog check complete: {match.value}",
                data={
                    "match": match.value,
                    "candidates_count": len(all_candidates),
                    "candidate_sets": candidate_sets.to_dict(),
                },
            )

        except Exception as e:
            logger.exception(f"Catalog lookup failed for {request.request_id}")

            # Log failure event
            self.db.add_event(
                request.request_id,
                EventType.BOT_CATALOG_CHECKED,
                payload={"match": "none", "error": str(e)},
            )

            return StageResult(
                success=False,
                message=f"Catalog lookup failed: {e}",
                data={"match": "none", "error": str(e)},
            )

    def _describe_search_strategy(self, evidence: EvidencePacket) -> str:
        """Describe the search strategy used."""
        if evidence.identifiers.isbn:
            return "isbn"
        elif evidence.extracted.title_guess and evidence.extracted.author_guess:
            return "title_author"
        elif evidence.extracted.title_guess:
            return "title_only"
        return "none"


class OpenLibraryEnrichmentStage(PipelineStage):
    """Stage 1.5: Enrich with metadata from Open Library.

    Runs after CatalogLookupStage for items not found in local catalog.
    Provides authoritative metadata (title, author, subjects, cover images)
    from Open Library's free API.
    """

    name = "openlibrary_enrichment"

    def __init__(self, config: BotConfig, db: BotDatabase, ol_client=None):
        super().__init__(config, db)
        self._ol_client = ol_client

    def is_enabled(self) -> bool:
        return (
            self.config.stages.openlibrary_enrichment
            and self.config.openlibrary.enabled
        )

    def _get_client(self) -> OpenLibraryClient:
        """Get or create Open Library client."""
        if self._ol_client is not None:
            return self._ol_client
        return OpenLibraryClient(
            timeout_seconds=self.config.openlibrary.timeout_seconds,
            max_search_results=self.config.openlibrary.max_search_results,
        )

    def _should_enrich(self, request: PurchaseRequest) -> tuple[bool, str]:
        """Determine if we should enrich this request."""
        catalog_match = request.catalog_match

        # Already enriched
        if request.openlibrary_checked_ts:
            return False, "already_checked"

        # No catalog check yet (shouldn't happen in normal flow)
        if not request.catalog_checked_ts:
            return False, "no_catalog_check"

        # Check based on catalog match result
        if catalog_match == CatalogMatch.NONE.value:
            if self.config.openlibrary.run_on_no_catalog_match:
                return True, "no_catalog_match"
            return False, "skip_no_match"

        if catalog_match == CatalogMatch.PARTIAL.value:
            if self.config.openlibrary.run_on_partial_catalog_match:
                return True, "partial_catalog_match"
            return False, "skip_partial_match"

        if catalog_match == CatalogMatch.EXACT.value:
            if self.config.openlibrary.run_on_exact_catalog_match:
                return True, "exact_catalog_match"
            return False, "skip_exact_match"

        return False, "unknown_match_type"

    async def process(self, request: PurchaseRequest) -> StageResult:
        """
        Enrich request with Open Library metadata.

        Uses evidence packet to search Open Library for metadata.
        """
        logger.info(f"Open Library enrichment for request {request.request_id}")

        # Check if we should enrich
        should_enrich, reason = self._should_enrich(request)
        if not should_enrich:
            logger.debug(
                f"Skipping Open Library enrichment for {request.request_id}: {reason}"
            )
            return StageResult(
                success=True,
                message=f"Skipped: {reason}",
                data={"skipped": True, "reason": reason},
            )

        # Get evidence packet
        evidence_dict = request.evidence_packet
        if not evidence_dict:
            logger.warning(
                f"No evidence packet for {request.request_id}, skipping enrichment"
            )
            return StageResult(
                success=True,
                message="Skipped: no evidence packet",
                data={"skipped": True, "reason": "no_evidence_packet"},
            )

        try:
            evidence = EvidencePacket.from_dict(evidence_dict)

            # Get search criteria from evidence
            isbn = evidence.identifiers.isbn[0] if evidence.identifiers.isbn else None
            title = evidence.extracted.title_guess
            author = evidence.extracted.author_guess

            if not self.config.openlibrary.allow_pii:
                isbn = scrub_pii(isbn)
                title = scrub_pii(title)
                author = scrub_pii(author)

            if not isbn and not title:
                logger.info(
                    f"No searchable criteria for {request.request_id}, skipping"
                )
                self.db.add_event(
                    request.request_id,
                    EventType.BOT_OPENLIBRARY_CHECKED,
                    payload={
                        "found": False,
                        "skipped": True,
                        "reason": "no_search_criteria",
                    },
                )
                return StageResult(
                    success=True,
                    message="Skipped: no searchable criteria",
                    data={"skipped": True, "reason": "no_search_criteria"},
                )

            # Call Open Library API
            client = self._get_client()
            enrichment = await enrich_from_openlibrary(
                client=client,
                isbn=isbn,
                title=title,
                author=author,
            )

            # Determine if we found something
            found = (
                enrichment.edition is not None
                or enrichment.match_confidence in ("high", "medium")
            )

            # Save results
            self.db.save_openlibrary_result(
                request.request_id,
                found=found,
                enrichment=enrichment.to_dict(),
            )

            # Build event summary
            event_payload = {
                "found": found,
                "match_confidence": enrichment.match_confidence,
                "source_query": enrichment.source_query,
            }

            if enrichment.edition:
                event_payload["edition_title"] = enrichment.edition.title
                event_payload["edition_key"] = enrichment.edition.key
                if enrichment.edition.authors:
                    event_payload["authors"] = [
                        a.name or a.key for a in enrichment.edition.authors
                    ]

            if enrichment.work:
                event_payload["work_key"] = enrichment.work.key
                if enrichment.work.subjects:
                    event_payload["subjects"] = enrichment.work.subjects[:5]

            if enrichment.error:
                event_payload["error"] = enrichment.error

            self.db.add_event(
                request.request_id,
                EventType.BOT_OPENLIBRARY_CHECKED,
                payload=event_payload,
            )

            logger.info(
                f"Open Library enrichment for {request.request_id}: "
                f"found={found}, confidence={enrichment.match_confidence}"
            )

            return StageResult(
                success=True,
                message=f"Enrichment complete: {'found' if found else 'not found'}",
                data={
                    "found": found,
                    "match_confidence": enrichment.match_confidence,
                    "enrichment": enrichment.to_dict(),
                },
            )

        except Exception as e:
            logger.exception(f"Open Library enrichment failed for {request.request_id}")

            # Log failure event
            self.db.add_event(
                request.request_id,
                EventType.BOT_OPENLIBRARY_CHECKED,
                payload={"found": False, "error": str(e)},
            )

            return StageResult(
                success=False,
                message=f"Enrichment failed: {e}",
                data={"found": False, "error": str(e)},
            )


class ConsortiumCheckStage(PipelineStage):
    """Stage 2: Check availability in OhioLINK/SearchOHIO."""

    name = "consortium_check"

    def is_enabled(self) -> bool:
        return self.config.stages.consortium_check

    async def process(self, request: PurchaseRequest) -> StageResult:
        """
        Search consortium catalogs for availability.

        TODO: Implement actual OhioLINK/SearchOHIO API calls.
        """
        logger.info(f"Consortium check for request {request.request_id}")

        # TODO: Implement real consortium search
        # Placeholder for now
        available = False
        sources: list[dict] = []

        self.db.save_consortium_result(request.request_id, available, sources)

        self.db.add_event(
            request.request_id,
            EventType.BOT_CONSORTIUM_CHECKED,
            payload={"available": available, "sources_count": len(sources)},
        )

        return StageResult(
            success=True,
            message=f"Consortium check complete: {'available' if available else 'not found'}",
            data={"available": available, "sources": sources},
        )


class InputRefinementStage(PipelineStage):
    """Stage 3: Use LLM to parse and refine patron input."""

    name = "input_refinement"

    def is_enabled(self) -> bool:
        return self.config.stages.input_refinement

    async def process(self, request: PurchaseRequest) -> StageResult:
        """
        Use LLM with tool calls to normalize patron input.

        TODO: Implement LLM integration.
        """
        logger.info(f"Input refinement for request {request.request_id}")

        # TODO: Implement LLM-based refinement
        # Placeholder for now

        self.db.add_event(
            request.request_id,
            EventType.BOT_REFINED,
            payload={"raw_query": request.raw_query},
        )

        return StageResult(
            success=True,
            message="Input refinement skipped (LLM not configured)",
        )


class SelectionGuidanceStage(PipelineStage):
    """Stage 4: Generate assessment based on collection guidelines."""

    name = "selection_guidance"

    def is_enabled(self) -> bool:
        return self.config.stages.selection_guidance

    async def process(self, request: PurchaseRequest) -> StageResult:
        """
        Use LLM to generate selection guidance for staff.

        TODO: Implement LLM integration with collection policy.
        """
        logger.info(f"Selection guidance for request {request.request_id}")

        # TODO: Implement LLM-based assessment
        # Placeholder for now

        self.db.add_event(
            request.request_id,
            EventType.BOT_ASSESSED,
            payload={},
        )

        return StageResult(
            success=True,
            message="Selection guidance skipped (LLM not configured)",
        )


class AutomaticActionsStage(PipelineStage):
    """Stage 5: Take automatic actions based on findings."""

    name = "automatic_actions"

    def is_enabled(self) -> bool:
        return self.config.stages.automatic_actions

    async def process(self, request: PurchaseRequest) -> StageResult:
        """
        Take automatic actions based on pipeline findings.

        Actions are configurable and all off by default.
        """
        logger.info(f"Automatic actions for request {request.request_id}")

        actions_taken: list[str] = []

        # Check for auto-decline on exact catalog match
        if (
            self.config.auto_actions.decline_on_catalog_exact_match
            and request.catalog_match == CatalogMatch.EXACT.value
        ):
            # TODO: Implement auto-decline
            logger.info(f"Would auto-decline {request.request_id} (exact catalog match)")
            actions_taken.append("auto_decline_suggested")

        # Check for auto-hold on consortium match
        if self.config.auto_actions.hold_on_consortium_match and request.consortium_available:
            # TODO: Implement ILL hold placement
            logger.info(f"Would place hold for {request.request_id} (consortium available)")
            actions_taken.append("hold_suggested")

        if actions_taken:
            self.db.add_event(
                request.request_id,
                EventType.BOT_ACTION_TAKEN,
                payload={"actions": actions_taken},
            )

        return StageResult(
            success=True,
            message=f"Actions evaluated: {actions_taken or 'none'}",
            data={"actions": actions_taken},
        )


class Pipeline:
    """
    The main processing pipeline for suggest-a-bot.

    Runs requests through each enabled stage in sequence.
    """

    def __init__(
        self,
        config: BotConfig,
        db: BotDatabase,
        sierra_client=None,
        ol_client=None,
    ):
        """
        Initialize the pipeline.

        Args:
            config: Bot configuration
            db: Database operations
            sierra_client: Optional SierraClient for catalog lookups (for testing)
            ol_client: Optional OpenLibraryClient for enrichment (for testing)
        """
        self.config = config
        self.db = db
        self.stages: list[PipelineStage] = [
            EvidenceExtractionStage(config, db),  # Always first - foundation
            CatalogLookupStage(config, db, sierra_client),
            OpenLibraryEnrichmentStage(config, db, ol_client),
            ConsortiumCheckStage(config, db),
            InputRefinementStage(config, db),
            SelectionGuidanceStage(config, db),
            AutomaticActionsStage(config, db),
        ]

    async def process_request(self, request: PurchaseRequest) -> bool:
        """
        Process a single request through all enabled stages.

        Returns True if processing completed successfully.
        """
        logger.info(f"Processing request {request.request_id}")

        # Mark as processing
        self.db.mark_processing(request.request_id)
        self.db.add_event(request.request_id, EventType.BOT_STARTED)

        try:
            for stage in self.stages:
                if not stage.is_enabled():
                    logger.debug(f"Skipping disabled stage: {stage.name}")
                    continue

                logger.info(f"Running stage: {stage.name}")
                result = await stage.process(request)

                if not result.success:
                    logger.warning(f"Stage {stage.name} failed: {result.message}")
                    # Continue to next stage even on failure (non-blocking)

                # Refresh request data for next stage
                request = self.db.get_request(request.request_id) or request

            # Mark as completed
            self.db.mark_completed(request.request_id)
            self.db.add_event(request.request_id, EventType.BOT_COMPLETED)

            logger.info(f"Completed processing request {request.request_id}")
            return True

        except Exception as e:
            logger.exception(f"Error processing request {request.request_id}")
            self.db.mark_error(request.request_id, str(e))
            self.db.add_event(
                request.request_id,
                EventType.BOT_ERROR,
                payload={"error": str(e)},
            )
            return False
