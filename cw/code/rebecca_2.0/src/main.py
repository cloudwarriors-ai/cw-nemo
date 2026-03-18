#!/usr/bin/env python3
"""
QA Continuity Agent - Main Entry Point

Fetches GitHub issues and posts a consolidated report to Zoom.
Run manually or via Windows Task Scheduler / cron.

Usage:
    python -m src.main
    python -m src.main --hygiene  # Hygiene report only
    python -m src.main --dry-run  # Print report without sending

Exit Codes:
    0 - Success
    1 - Configuration error
    2 - GitHub API error
    3 - Zoom notification error
    4 - Rate limited
    5 - Unknown error
"""
import argparse
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from .github_client import GitHubClient
from .report_generator import ReportGenerator
from .zoom_notifier import ZoomNotifier
from .utils import (
    ExitCode,
    setup_logging,
    validate_token_format,
    redact_token,
)

# Load environment variables from .env file
load_dotenv()

# Configuration from environment
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
ZOOM_WEBHOOK_URL = os.getenv("ZOOM_WEBHOOK_URL")
GITHUB_ORG = os.getenv("GITHUB_ORG", "cloudwarriors-ai")
LOG_DIR = os.getenv("LOG_DIR", "logs")

# Repositories to monitor - add your repos here
REPOS = [
    # "repo-name-1",
    # "repo-name-2",
    # Add repository names (without org prefix)
]


def validate_config(logger):
    """
    Validate required configuration is present.

    Args:
        logger: Logger instance

    Returns:
        True if valid, exits with error code if not
    """
    errors = []

    # Validate GitHub token
    try:
        validate_token_format(GITHUB_TOKEN, "GITHUB_TOKEN")
        logger.debug(f"GitHub token: {redact_token(GITHUB_TOKEN)}")
    except ValueError as e:
        errors.append(str(e))

    # Validate repos
    if not REPOS:
        errors.append("No repositories configured. Edit REPOS list in main.py")

    if errors:
        logger.error("Configuration errors:")
        for error in errors:
            logger.error(f"  - {error}")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Warn about optional config
    if not ZOOM_WEBHOOK_URL:
        logger.warning("ZOOM_WEBHOOK_URL not set. Reports will print to console only.")

    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="QA Continuity Agent - GitHub Issue Reporter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0  Success
  1  Configuration error
  2  GitHub API error
  3  Zoom notification error
  4  Rate limited
  5  Unknown error

Examples:
  python -m src.main                    # Weekly report
  python -m src.main --hygiene          # Hygiene report
  python -m src.main --dry-run          # Test without sending
  python -m src.main --show-rate-limit  # Check API limits
        """
    )
    parser.add_argument(
        "--hygiene",
        action="store_true",
        help="Generate hygiene report instead of weekly report"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print report without sending to Zoom"
    )
    parser.add_argument(
        "--show-rate-limit",
        action="store_true",
        help="Show GitHub API rate limit status"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (debug) logging"
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Disable logging to file (console only)"
    )
    args = parser.parse_args()

    # Setup logging
    import logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_dir = None if args.no_log_file else LOG_DIR
    logger = setup_logging(log_dir=log_dir, level=log_level)

    logger.info("=" * 50)
    logger.info(f"QA Continuity Agent - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    try:
        # Validate configuration
        validate_config(logger)

        # Initialize clients
        github_client = GitHubClient(
            token=GITHUB_TOKEN,
            org=GITHUB_ORG,
            logger=logger
        )
        report_generator = ReportGenerator()
        zoom_notifier = ZoomNotifier(
            webhook_url=None if args.dry_run else ZOOM_WEBHOOK_URL,
            logger=logger
        )

        # Show rate limit if requested
        if args.show_rate_limit:
            try:
                rate_limit = github_client.get_rate_limit_status()
                logger.info(f"GitHub API Rate Limit: {rate_limit['remaining']}/{rate_limit['limit']}")
                logger.info(f"Resets at: {rate_limit['reset_time']}")

                # Warn if low
                if rate_limit['remaining'] < 500:
                    logger.warning("Rate limit is getting low!")
            except Exception as e:
                logger.error(f"Could not fetch rate limit: {e}")

        # Fetch issues
        logger.info(f"Fetching issues from {len(REPOS)} repositories...")
        issues = github_client.fetch_issues(REPOS)
        logger.info(f"Found {len(issues)} open issues")

        if not issues and not args.dry_run:
            logger.warning("No issues found. Report may be empty.")

        # Generate report
        report_type = "hygiene" if args.hygiene else "weekly"
        logger.info(f"Generating {report_type} report...")

        if args.hygiene:
            report = report_generator.generate_hygiene_report(issues)
        else:
            report = report_generator.generate_weekly_report(issues)

        # Send or print report
        if args.dry_run:
            logger.info("DRY RUN - Report output:")
            print("=" * 50)
            print(report)
            print("=" * 50)
            logger.info("Dry run complete. No report sent.")
            sys.exit(ExitCode.SUCCESS)
        else:
            try:
                success = zoom_notifier.send_with_fallback(report)
                if success:
                    logger.info("Report delivered successfully")
                    sys.exit(ExitCode.SUCCESS)
                else:
                    logger.warning("Report saved to fallback file (Zoom delivery failed)")
                    sys.exit(ExitCode.ZOOM_ERROR)
            except Exception as e:
                logger.critical(f"Failed to deliver report: {e}")
                sys.exit(ExitCode.ZOOM_ERROR)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(ExitCode.SUCCESS)

    except Exception as e:
        logger.critical(f"Unexpected error: {e}", exc_info=True)
        sys.exit(ExitCode.UNKNOWN_ERROR)


if __name__ == "__main__":
    main()
