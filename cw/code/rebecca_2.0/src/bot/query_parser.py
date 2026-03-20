"""
Query parser for interpreting user requests.

Uses keyword matching as primary method with optional LLM fallback
for natural language queries that don't match patterns.
"""
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class QueryType(Enum):
    """Types of queries the bot can handle."""
    HIGH_PRIORITY = "high_priority"
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    STALE = "stale"
    HYGIENE = "hygiene"
    SUMMARY = "summary"
    REPO_FILTER = "repo_filter"
    ASSIGNEE_FILTER = "assignee_filter"
    INTERN_STATUS = "intern_status"
    ONBOARDING = "onboarding"
    HELP = "help"
    ESCALATE = "escalate"
    UNKNOWN = "unknown"


@dataclass
class QueryResult:
    """Parsed query with extracted parameters."""
    query_type: QueryType
    repo: Optional[str] = None
    assignee: Optional[str] = None
    intern_name: Optional[str] = None
    topic: Optional[str] = None  # For escalation
    confidence: float = 1.0
    raw_text: str = ""

    # Additional filters that can be combined
    filters: dict = field(default_factory=dict)


class QueryParser:
    """
    Parse user queries into structured QueryResult objects.

    Uses keyword matching for defined patterns. Falls back to
    LLM classification when keywords don't match and LLM client
    is configured.
    """

    # Keyword patterns for each query type
    PATTERNS = {
        QueryType.HIGH_PRIORITY: [
            r"\bhigh\s*priority\b",
            r"\bhigh\s*pri\b",
            r"\bp1\b",
            r"\bpriority\s*high\b",
            r"\burgent\b",
            r"\bcritical\b",
        ],
        QueryType.UNASSIGNED: [
            r"\bunassigned\b",
            r"\bno\s*assignee\b",
            r"\bneeds\s*owner\b",
            r"\borphan\b",
        ],
        QueryType.ASSIGNED: [
            r"\bassigned\b",
            r"\bhas\s*assignee\b",
            r"\bwho.*assigned\b",
            r"\bowned\b",
        ],
        QueryType.STALE: [
            r"\bstale\b",
            r"\bold\s*issues?\b",
            r"\binactive\b",
            r"\bno\s*update\b",
            r"\bneglected\b",
        ],
        QueryType.HYGIENE: [
            r"\bhygiene\b",
            r"\bhealth\s*check\b",
            r"\bmissing\s*(labels?|fields?)\b",
            r"\bproblems?\b",
        ],
        QueryType.SUMMARY: [
            r"\bsummary\b",
            r"\boverview\b",
            r"\ball\s*issues?\b",
            r"\btotal\b",
            r"\bcount\b",
            r"\bstatus\s*report\b",
        ],
        QueryType.INTERN_STATUS: [
            r"\bintern\s*(status|progress|update)\b",
            r"\bintern\s+\w+\s+(status|progress|update)\b",  # intern [name] status
            r"\bhow\s*(is|are)\s*(the\s*)?intern",
            r"\bintern\s*check\b",
        ],
        QueryType.ONBOARDING: [
            r"\bonboarding\b",
            r"\bnew\s*hire\b",
            r"\bgetting\s*started\b",
            r"\bchange\s*control\b",
            r"\bcab\s*(review|process)\b",
            r"\bweekly\s*checklist\b",
            r"\bissue\s*(management|guide|tracking)\b",
            r"\bkey\s*contacts?\b",
            r"\bmeeting\s*schedule\b",
            r"\bskillbridge\b",
            r"\bdocs?\s*(link|reference)\b",
        ],
        QueryType.HELP: [
            r"^\s*help\s*$",
            r"\bwhat\s*can\s*you\s*do\b",
            r"\bcommands?\b",
            r"\bhow\s*do\s*i\b",
        ],
        QueryType.ESCALATE: [
            r"\bescalate\b",
            r"\btalk\s*to\s*(a\s*)?human\b",
            r"\bneed\s*(a\s*)?person\b",
            r"\bget\s*help\b",
            r"\bhuman\s*help\b",
        ],
    }

    # Sensitive topics that should trigger escalation
    SENSITIVE_TOPICS = [
        "performance review", "performance evaluation", "job performance",
        "evaluation", "termination", "conflict",
        "complaint", "harassment", "discrimination", "firing",
        "salary", "compensation", "promotion", "demotion",
        "disciplinary", "warning", "probation",
    ]

    def __init__(self, llm_client=None, logger: logging.Logger = None):
        """
        Initialize the query parser.

        Args:
            llm_client: Optional LLM client for natural language fallback
            logger: Logger instance
        """
        self.llm_client = llm_client
        self.logger = logger or logging.getLogger("qa_agent")

        # Compile regex patterns for efficiency
        self._compiled_patterns = {
            query_type: [re.compile(p, re.IGNORECASE) for p in patterns]
            for query_type, patterns in self.PATTERNS.items()
        }

        # Compile sensitive topic patterns with word boundaries
        self._sensitive_patterns = [
            re.compile(r"\b" + re.escape(topic) + r"\b", re.IGNORECASE)
            for topic in self.SENSITIVE_TOPICS
        ]

    def parse(self, text: str) -> QueryResult:
        """
        Parse user query into a structured result.

        Args:
            text: Raw user input text

        Returns:
            QueryResult with query type and extracted parameters
        """
        if not text or not text.strip():
            return QueryResult(
                query_type=QueryType.HELP,
                raw_text=text or "",
                confidence=1.0
            )

        text = text.strip()
        text_lower = text.lower()

        # Check for sensitive topics first - always escalate
        if self._contains_sensitive_topic(text):
            return QueryResult(
                query_type=QueryType.ESCALATE,
                topic=text,
                raw_text=text,
                confidence=1.0
            )

        # Try keyword matching first
        result = self._match_keywords(text, text_lower)
        if result:
            # Extract additional filters (repo, assignee)
            result = self._extract_filters(result, text_lower)
            return result

        # If no keyword match and LLM is available, try LLM classification
        if self.llm_client:
            result = self._classify_with_llm(text)
            if result.confidence > 0.7:
                result = self._extract_filters(result, text_lower)
                return result

        # Unknown query - will trigger help response
        return QueryResult(
            query_type=QueryType.UNKNOWN,
            raw_text=text,
            confidence=0.0
        )

    def _contains_sensitive_topic(self, text: str) -> bool:
        """Check if text contains sensitive topics requiring escalation.

        Uses word boundaries to avoid false positives (e.g., 'performance'
        in 'high-performance' won't trigger escalation).
        """
        return any(pattern.search(text) for pattern in self._sensitive_patterns)

    def _match_keywords(self, text: str, text_lower: str) -> Optional[QueryResult]:
        """
        Match text against keyword patterns.

        Returns QueryResult if a pattern matches, None otherwise.
        """
        for query_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(text_lower):
                    return QueryResult(
                        query_type=query_type,
                        raw_text=text,
                        confidence=1.0
                    )
        return None

    def _extract_filters(self, result: QueryResult, text_lower: str) -> QueryResult:
        """
        Extract additional filters (repo, assignee) from the query.

        Modifies and returns the result with extracted filters.
        """
        # Extract repo filter: "repo:name" or "in repo name"
        repo_match = re.search(r"repo[:\s]+(\w+)", text_lower)
        if repo_match:
            result.repo = repo_match.group(1)
        else:
            in_repo_match = re.search(r"in\s+(\w+)\s+repo", text_lower)
            if in_repo_match:
                result.repo = in_repo_match.group(1)

        # Extract assignee filter: "assigned to name" or "assignee:name"
        assignee_match = re.search(r"assigned\s+to\s+(\w+)", text_lower)
        if assignee_match:
            result.assignee = assignee_match.group(1)
        else:
            assignee_alt = re.search(r"assignee[:\s]+(\w+)", text_lower)
            if assignee_alt:
                result.assignee = assignee_alt.group(1)

        # Extract intern name for intern status queries
        if result.query_type == QueryType.INTERN_STATUS:
            intern_match = re.search(r"intern\s+(\w+)", text_lower)
            if intern_match and intern_match.group(1) not in ["status", "progress", "update", "check"]:
                result.intern_name = intern_match.group(1)

        return result

    def _classify_with_llm(self, text: str) -> QueryResult:
        """
        Use LLM to classify natural language query.

        Returns QueryResult with lower confidence if LLM is uncertain.
        """
        try:
            # Build classification prompt
            prompt = f"""Classify this user query into one of these categories:
- high_priority: asking about high priority issues
- unassigned: asking about unassigned issues
- stale: asking about old/inactive issues
- hygiene: asking about issue health/problems
- summary: asking for overview or counts
- intern_status: asking about intern progress
- help: asking what the bot can do
- escalate: needs human help
- unknown: doesn't fit any category

Query: "{text}"

Respond with just the category name and a confidence score 0-1, e.g.:
summary 0.9"""

            response = self.llm_client.classify(prompt)

            # Parse response
            parts = response.strip().split()
            if len(parts) >= 2:
                category = parts[0].lower()
                confidence = float(parts[1])

                # Map to QueryType
                type_map = {
                    "high_priority": QueryType.HIGH_PRIORITY,
                    "unassigned": QueryType.UNASSIGNED,
                    "stale": QueryType.STALE,
                    "hygiene": QueryType.HYGIENE,
                    "summary": QueryType.SUMMARY,
                    "intern_status": QueryType.INTERN_STATUS,
                    "help": QueryType.HELP,
                    "escalate": QueryType.ESCALATE,
                }

                query_type = type_map.get(category, QueryType.UNKNOWN)
                return QueryResult(
                    query_type=query_type,
                    raw_text=text,
                    confidence=confidence
                )

        except Exception as e:
            self.logger.warning(f"LLM classification failed: {e}")

        return QueryResult(
            query_type=QueryType.UNKNOWN,
            raw_text=text,
            confidence=0.0
        )
