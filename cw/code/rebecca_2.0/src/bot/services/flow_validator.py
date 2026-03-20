"""
Flow field validation service.

Handles validation of all fields in onboarding/offboarding flows.
Extracted from ConversationFlowHandler for separation of concerns.
"""
import re
import logging
from datetime import datetime, timedelta
from typing import Optional


class FlowValidatorService:
    """
    Service for validating flow field values.

    Provides validation for:
    - Names (format, length)
    - Emails (format, domain restrictions)
    - GitHub usernames (format)
    - Programs (allowed values)
    - Dates (format, range)
    - Meeting timing options
    - Offboarding reasons
    """

    # Validation constants
    MIN_NAME_LENGTH = 2
    MAX_NAME_LENGTH = 100
    MAX_GITHUB_USERNAME_LENGTH = 39

    # Valid programs
    VALID_PROGRAMS = ["skillbridge", "vanderbilt", "other"]

    # Meeting timing aliases
    NOW_ALIASES = ("now", "immediately", "today", "yes")
    LATER_ALIASES = ("later", "start date", "on start date", "wait", "no", "last day")

    # Offboard reason mappings
    OFFBOARD_REASON_MAP = {
        "end of program": "end_of_program",
        "end program": "end_of_program",
        "program end": "end_of_program",
        "voluntary": "voluntary",
        "quit": "voluntary",
        "resigned": "voluntary",
        "other": "other",
    }

    def __init__(
        self,
        allowed_email_domains: Optional[list[str]] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the validator service.

        Args:
            allowed_email_domains: List of allowed email domains (empty = all allowed)
            logger: Logger instance
        """
        self.allowed_email_domains = allowed_email_domains or []
        self.logger = logger or logging.getLogger(__name__)

    def validate_field(self, validator: str, value: str, collected: dict = None) -> dict:
        """
        Validate a field value based on validator type.

        Args:
            validator: Validator type (name, email, github, program, date, etc.)
            value: Value to validate
            collected: Currently collected data (for context-aware validation)

        Returns:
            Dict with:
                - valid: bool - Whether validation passed
                - value: str - Cleaned/normalized value (if valid)
                - error: str - Error message (if invalid)
        """
        value = value.strip()

        validators = {
            "name": self.validate_name,
            "email": self.validate_email,
            "github": self.validate_github,
            "program": self.validate_program,
            "date": self.validate_date,
            "meetings_timing": self.validate_meetings_timing,
            "last_day": self.validate_last_day,
            "offboard_reason": self.validate_offboard_reason,
        }

        if validator in validators:
            return validators[validator](value)

        # Unknown validator - accept as-is
        self.logger.debug(f"Unknown validator '{validator}', accepting value as-is")
        return {"valid": True, "value": value}

    def validate_name(self, value: str) -> dict:
        """Validate a person's name."""
        value = value.strip()

        if len(value) < self.MIN_NAME_LENGTH:
            return {
                "valid": False,
                "error": f"Name must be at least {self.MIN_NAME_LENGTH} characters."
            }

        if len(value) > self.MAX_NAME_LENGTH:
            return {"valid": False, "error": "Name is too long."}

        # Basic name validation - letters, spaces, hyphens, apostrophes, periods
        if not re.match(r"^[a-zA-Z\s\-'\.]+$", value):
            return {"valid": False, "error": "Name contains invalid characters."}

        return {"valid": True, "value": value.title()}

    def validate_email(self, value: str) -> dict:
        """Validate an email address."""
        value = value.strip()
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

        if not re.match(email_pattern, value):
            return {"valid": False, "error": "Invalid email format."}

        # Check domain if restricted
        if self.allowed_email_domains:
            domain = value.split("@")[1].lower()
            if domain not in [d.lower() for d in self.allowed_email_domains]:
                domains = ", ".join(self.allowed_email_domains)
                return {
                    "valid": False,
                    "error": f"Email must be from: {domains}"
                }

        return {"valid": True, "value": value.lower()}

    def validate_github(self, value: str) -> dict:
        """Validate a GitHub username."""
        value = value.strip()

        # GitHub username rules: alphanumeric and hyphens, no consecutive hyphens
        if not re.match(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$", value):
            return {"valid": False, "error": "Invalid GitHub username format."}

        if len(value) > self.MAX_GITHUB_USERNAME_LENGTH:
            return {"valid": False, "error": "GitHub username too long."}

        return {"valid": True, "value": value}

    def validate_program(self, value: str) -> dict:
        """Validate a program selection."""
        value_lower = value.strip().lower()

        if value_lower not in self.VALID_PROGRAMS:
            programs_str = ", ".join(self.VALID_PROGRAMS)
            return {"valid": False, "error": f"Program must be one of: {programs_str}"}

        return {"valid": True, "value": value_lower}

    def validate_date(self, value: str) -> dict:
        """Validate a date (for start dates)."""
        value = value.strip()

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return {"valid": False, "error": "Date must be in YYYY-MM-DD format."}

        try:
            date = datetime.strptime(value, "%Y-%m-%d")
            today = datetime.now()

            # Don't allow dates too far in past or future
            if date < today.replace(year=today.year - 1):
                return {
                    "valid": False,
                    "error": "Start date cannot be more than 1 year in the past."
                }

            if date > today.replace(year=today.year + 1):
                return {
                    "valid": False,
                    "error": "Start date cannot be more than 1 year in the future."
                }

            return {"valid": True, "value": value}

        except ValueError:
            return {"valid": False, "error": "Invalid date."}

    def validate_meetings_timing(self, value: str) -> dict:
        """Validate meeting timing option (now/later)."""
        value_lower = value.strip().lower()

        if value_lower in self.NOW_ALIASES:
            return {"valid": True, "value": "now"}

        if value_lower in self.LATER_ALIASES:
            return {"valid": True, "value": "later"}

        return {"valid": False, "error": "Please reply 'now' or 'later'."}

    def validate_last_day(self, value: str) -> dict:
        """Validate last day date (for offboarding)."""
        value_lower = value.strip().lower()

        # Handle 'today' alias
        if value_lower in ("today", "now"):
            return {"valid": True, "value": datetime.now().strftime("%Y-%m-%d")}

        # Check date format
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return {
                "valid": False,
                "error": "Date must be in YYYY-MM-DD format or 'today'."
            }

        try:
            date = datetime.strptime(value, "%Y-%m-%d")
            today = datetime.now()

            # Last day can be in the past (already left) or up to 30 days in future
            if date < today.replace(year=today.year - 1):
                return {
                    "valid": False,
                    "error": "Last day cannot be more than 1 year in the past."
                }

            if date > today.replace(day=today.day) + timedelta(days=30):
                return {
                    "valid": False,
                    "error": "Last day cannot be more than 30 days in the future."
                }

            return {"valid": True, "value": value}

        except ValueError:
            return {"valid": False, "error": "Invalid date."}

    def validate_offboard_reason(self, value: str) -> dict:
        """Validate offboarding reason."""
        value_lower = value.strip().lower()

        for key, normalized in self.OFFBOARD_REASON_MAP.items():
            if key in value_lower:
                return {"valid": True, "value": normalized}

        return {
            "valid": False,
            "error": "Reason must be: end of program, voluntary, or other."
        }
