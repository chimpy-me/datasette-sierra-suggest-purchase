"""
CLI runner for suggest-a-bot.

Usage:
    python -m suggest_a_bot.run [OPTIONS]

    # Process all pending requests once
    python -m suggest_a_bot.run --once

    # Run as daemon with schedule
    python -m suggest_a_bot.run --daemon

    # Process a specific request
    python -m suggest_a_bot.run --request-id abc123
"""

import argparse
import asyncio
import contextlib
import logging
import sys
from pathlib import Path

from .config import BotConfig
from .models import BotDatabase, RunStatus
from .pipeline import Pipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("suggest-a-bot")


async def run_once(config: BotConfig) -> tuple[int, int]:
    """
    Process all pending requests once.

    Returns (processed_count, error_count).
    """
    db = BotDatabase(config.db_path)
    pipeline = Pipeline(config, db)

    # Create a run record
    run = db.create_run(config.to_dict())
    logger.info(f"Starting run {run.run_id}")

    processed = 0
    errored = 0

    try:
        # Get pending requests
        requests = db.get_pending_requests(limit=config.max_requests_per_run)
        logger.info(f"Found {len(requests)} pending request(s)")

        for request in requests:
            success = await pipeline.process_request(request)
            if success:
                processed += 1
            else:
                errored += 1

        # Complete the run
        db.complete_run(run.run_id, processed, errored, RunStatus.COMPLETED)
        logger.info(f"Run {run.run_id} completed: {processed} processed, {errored} errors")

    except Exception as e:
        logger.exception("Run failed with error")
        db.complete_run(run.run_id, processed, errored, RunStatus.FAILED, str(e))
        raise

    return processed, errored


async def process_single(config: BotConfig, request_id: str) -> bool:
    """Process a single request by ID."""
    db = BotDatabase(config.db_path)
    pipeline = Pipeline(config, db)

    request = db.get_request(request_id)
    if not request:
        logger.error(f"Request not found: {request_id}")
        return False

    logger.info(f"Processing single request: {request_id}")
    return await pipeline.process_request(request)


async def run_daemon(config: BotConfig) -> None:
    """
    Run as a daemon, processing requests on schedule.

    TODO: Implement proper scheduling with cron-like syntax.
    For now, just runs in a loop with a fixed interval.
    """
    logger.info("Starting suggest-a-bot daemon")
    logger.info(f"Schedule: {config.schedule}")
    logger.info(f"Database: {config.db_path}")

    # Parse simple interval from schedule (e.g., "*/15 * * * *" -> 15 minutes)
    # This is a simplified implementation; real cron parsing would be more complex
    interval_minutes = 15
    if config.schedule.startswith("*/"):
        with contextlib.suppress(ValueError, IndexError):
            interval_minutes = int(config.schedule.split()[0][2:])

    interval_seconds = interval_minutes * 60
    logger.info(f"Running every {interval_minutes} minutes")

    while True:
        try:
            processed, errored = await run_once(config)
            logger.info(f"Cycle complete: {processed} processed, {errored} errors")
        except Exception as e:
            logger.exception(f"Cycle failed: {e}")

        logger.info(f"Sleeping for {interval_minutes} minutes...")
        await asyncio.sleep(interval_seconds)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="suggest-a-bot: Automated purchase suggestion processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Process all pending requests once
    python -m suggest_a_bot.run --once

    # Run as daemon
    python -m suggest_a_bot.run --daemon

    # Process a specific request
    python -m suggest_a_bot.run --request-id abc123def456

    # Use a specific config file
    python -m suggest_a_bot.run --config datasette.yaml --once
        """,
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=Path("datasette.yaml"),
        help="Path to config file (default: datasette.yaml)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="Override database path from config",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process pending requests once and exit",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a daemon, processing on schedule",
    )
    parser.add_argument(
        "--request-id",
        type=str,
        help="Process a specific request by ID",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without making changes",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load config
    config = BotConfig.from_yaml(args.config)
    if args.db:
        config.db_path = args.db

    logger.info(f"Config loaded from {args.config}")
    logger.info(f"Database: {config.db_path}")
    logger.info(
        f"Stages enabled: catalog={config.stages.catalog_lookup}, "
        f"consortium={config.stages.consortium_check}, "
        f"refinement={config.stages.input_refinement}, "
        f"guidance={config.stages.selection_guidance}, "
        f"auto_actions={config.stages.automatic_actions}"
    )

    # Check database exists
    if not config.db_path.exists():
        logger.error(f"Database not found: {config.db_path}")
        logger.error("Run 'python scripts/init_db.py' first to create the database.")
        return 1

    # Dry run mode
    if args.dry_run:
        db = BotDatabase(config.db_path)
        requests = db.get_pending_requests(limit=config.max_requests_per_run)
        logger.info(f"Dry run: would process {len(requests)} request(s)")
        for req in requests:
            logger.info(f"  - {req.request_id}: {req.raw_query[:50]}...")
        return 0

    # Run mode selection
    if args.request_id:
        success = asyncio.run(process_single(config, args.request_id))
        return 0 if success else 1

    if args.daemon:
        try:
            asyncio.run(run_daemon(config))
        except KeyboardInterrupt:
            logger.info("Daemon stopped by user")
        return 0

    if args.once:
        processed, errored = asyncio.run(run_once(config))
        return 0 if errored == 0 else 1

    # Default: show help
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
