"""
Query context for encapsulating query-related parameters.

Replaces long parameter lists with a single context object,
improving readability and reducing parameter passing overhead.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QueryContext:
    """
    Context object for query processing.

    Encapsulates all parameters needed during query processing,
    replacing repeated parameter lists across handler functions.
    """
    text: str
    user_id: str
    user_name: str = ""
    channel_id: str = ""
    request_id: str = ""
    user_email: str = ""
    conversation_history: list = field(default_factory=list)

    @property
    def text_lower(self) -> str:
        """Return lowercase stripped text for comparisons."""
        return self.text.lower().strip()

    def log_prefix(self) -> str:
        """Return a prefix for log messages."""
        return f"[{self.request_id}]" if self.request_id else ""
