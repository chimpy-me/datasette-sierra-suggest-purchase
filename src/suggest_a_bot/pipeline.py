"""
Processing pipeline for suggest-a-bot.

Each stage in the pipeline enriches the purchase request with additional
information that helps staff make decisions.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .config import BotConfig
from .models import (
    BotDatabase,
    CatalogMatch,
    EventType,
    PurchaseRequest,
)

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


class CatalogLookupStage(PipelineStage):
    """Stage 1: Check if item exists in our catalog."""

    name = "catalog_lookup"

    def is_enabled(self) -> bool:
        return self.config.stages.catalog_lookup

    async def process(self, request: PurchaseRequest) -> StageResult:
        """
        Search the Sierra catalog for matching items.

        TODO: Implement actual Sierra API/DB lookup.
        For now, returns a placeholder result.
        """
        logger.info(f"Catalog lookup for request {request.request_id}: {request.raw_query}")

        # TODO: Implement real catalog search
        # This is a placeholder that demonstrates the interface

        # For now, always report no match (will be replaced with real lookup)
        match = CatalogMatch.NONE
        holdings: list[dict] = []

        # Save results
        self.db.save_catalog_result(request.request_id, match, holdings)

        # Log event
        self.db.add_event(
            request.request_id,
            EventType.BOT_CATALOG_CHECKED,
            payload={"match": match.value, "holdings_count": len(holdings)},
        )

        return StageResult(
            success=True,
            message=f"Catalog check complete: {match.value}",
            data={"match": match.value, "holdings": holdings},
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
        if (
            self.config.auto_actions.hold_on_consortium_match
            and request.consortium_available
        ):
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

    def __init__(self, config: BotConfig, db: BotDatabase):
        self.config = config
        self.db = db
        self.stages: list[PipelineStage] = [
            CatalogLookupStage(config, db),
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
