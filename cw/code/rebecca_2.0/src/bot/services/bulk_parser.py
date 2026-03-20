"""
Bulk submission parser for onboarding/offboarding forms.

Handles parsing of multi-field submissions and form template generation.
Extracted from ConversationFlowHandler for separation of concerns.
"""
import re
import logging
from typing import Optional


class BulkSubmissionParser:
    """
    Parser for bulk onboarding/offboarding submissions.

    Parses structured form data from text messages and provides
    form templates for users to fill out.
    """

    # Minimum fields required for valid bulk submission
    MIN_BULK_FIELDS_ONBOARDING = 3
    MIN_BULK_FIELDS_OFFBOARDING = 2

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the parser.

        Args:
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

    @staticmethod
    def get_intern_form_template() -> str:
        """
        Generate an intern onboarding form template.

        Returns:
            Formatted template string for bulk submission
        """
        return (
            "**Intern Onboarding Form**\n\n"
            "Copy and fill in the details below:\n\n"
            "```\n"
            "Name: \n"
            "Email: \n"
            "GitHub: \n"
            "Program: skillbridge / vanderbilt / other\n"
            "Start Date: YYYY-MM-DD\n"
            "Supervisor: \n"
            "Meetings: now / later\n"
            "```\n\n"
            "_Paste the completed form to onboard directly._"
        )

    @staticmethod
    def get_offboard_form_template() -> str:
        """
        Generate an intern offboarding form template.

        Returns:
            Formatted template string for bulk submission
        """
        return (
            "**Intern Offboarding Form**\n\n"
            "Copy and fill in the details below:\n\n"
            "```\n"
            "Name: [intern's full name]\n"
            "Last Day: YYYY-MM-DD or today\n"
            "Reason: end of program / voluntary / other\n"
            "Remove from Meetings: now / later\n"
            "```\n\n"
            "_Paste the completed form to offboard directly._"
        )

    def parse_bulk_submission(self, text: str) -> Optional[dict]:
        """
        Parse a bulk onboarding submission.

        Extracts fields from a formatted message like:
        Name: John Doe
        Email: john@example.com
        GitHub: johndoe
        Program: skillbridge
        Start Date: 2026-01-25
        Supervisor: Jane Smith

        Also handles inline format (when Zoom strips newlines):
        Name: John Doe Email: john@example.com GitHub: johndoe ...

        Args:
            text: Message text to parse

        Returns:
            Dict of parsed fields, or None if not a bulk submission
        """
        parsed = {}

        # Patterns that work with both newlines and inline (lookahead to next field or end)
        # All patterns are case-insensitive for field names
        field_patterns = [
            ("add_to_meetings", r"meetings?\s*:\s*(now|later|immediately|wait|yes|no)"),
            ("supervisor", r"supervisor\s*:\s*(.+?)(?=\s*(?:name|email|github|program|start\s*date|meetings?)\s*:|$)"),
            ("start_date", r"start\s*date\s*:\s*(\d{4}-\d{2}-\d{2})"),
            ("program", r"program\s*:\s*(skillbridge|vanderbilt|other)"),
            ("github_username", r"github\s*:\s*([a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)"),
            ("email", r"email\s*:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"),
            ("name", r"name\s*:\s*([A-Za-z][A-Za-z\s\-'\.]+?)(?=\s*(?:email|github|program|start\s*date|supervisor|meetings?)\s*:|$)"),
        ]

        for field, pattern in field_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                # Skip placeholder values
                if value and value.lower() not in ("", "yyyy-mm-dd", "skillbridge / vanderbilt / other"):
                    parsed[field] = value

        # Require minimum fields to consider it a bulk submission
        if len(parsed) >= self.MIN_BULK_FIELDS_ONBOARDING:
            self.logger.debug(f"Parsed bulk submission: {list(parsed.keys())}")
            return parsed

        return None

    def parse_bulk_offboarding(self, text: str) -> Optional[dict]:
        """
        Parse a bulk offboarding submission.

        Extracts fields from a formatted message like:
        Name: John Doe
        Last Day: 2026-01-25
        Reason: end of program
        Remove from Meetings: now

        Args:
            text: Message text to parse

        Returns:
            Dict of parsed fields, or None if not a bulk offboarding submission
        """
        parsed = {}

        # Patterns for offboarding fields
        field_patterns = [
            ("remove_from_meetings", r"remove\s*(?:from\s*)?meetings?\s*:\s*(now|later|immediately|wait|yes|no)"),
            ("reason", r"reason\s*:\s*(end\s*(?:of\s*)?program|voluntary|other|quit|resigned)"),
            ("last_day", r"last\s*day\s*:\s*(\d{4}-\d{2}-\d{2}|today)"),
            ("name", r"name\s*:\s*([A-Za-z][A-Za-z\s\-'\.]+?)(?=\s*(?:last\s*day|reason|remove|meetings?)\s*:|$)"),
        ]

        for field, pattern in field_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if value and value.lower() not in ("", "[intern's full name]"):
                    parsed[field] = value

        # Require at least name + other fields for offboarding
        if "name" in parsed and len(parsed) >= self.MIN_BULK_FIELDS_OFFBOARDING:
            self.logger.debug(f"Parsed bulk offboarding: {list(parsed.keys())}")
            return parsed

        return None

    def is_bulk_submission(self, text: str) -> bool:
        """
        Check if text appears to be a bulk submission.

        Args:
            text: Message text to check

        Returns:
            True if text looks like a bulk submission
        """
        return self.parse_bulk_submission(text) is not None

    def is_bulk_offboarding(self, text: str) -> bool:
        """
        Check if text appears to be a bulk offboarding submission.

        Args:
            text: Message text to check

        Returns:
            True if text looks like a bulk offboarding submission
        """
        return self.parse_bulk_offboarding(text) is not None
