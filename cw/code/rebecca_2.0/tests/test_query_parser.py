"""
Tests for QueryParser.
"""
import pytest
from src.bot.query_parser import QueryParser, QueryType, QueryResult


class TestQueryParserKeywords:
    """Test keyword pattern matching."""

    def test_high_priority_patterns(self, query_parser):
        """Test various high priority query patterns."""
        patterns = [
            "high priority",
            "high priority issues",
            "show me high pri",
            "p1 issues",
            "urgent issues",
            "critical bugs",
        ]
        for pattern in patterns:
            result = query_parser.parse(pattern)
            assert result.query_type == QueryType.HIGH_PRIORITY, f"Failed for: {pattern}"

    def test_unassigned_patterns(self, query_parser):
        """Test unassigned query patterns."""
        patterns = [
            "unassigned",
            "unassigned issues",
            "no assignee",
            "needs owner",
            "orphan issues",
        ]
        for pattern in patterns:
            result = query_parser.parse(pattern)
            assert result.query_type == QueryType.UNASSIGNED, f"Failed for: {pattern}"

    def test_stale_patterns(self, query_parser):
        """Test stale issue query patterns."""
        patterns = [
            "stale",
            "stale issues",
            "old issues",
            "inactive",
            "no update",
        ]
        for pattern in patterns:
            result = query_parser.parse(pattern)
            assert result.query_type == QueryType.STALE, f"Failed for: {pattern}"

    def test_hygiene_patterns(self, query_parser):
        """Test hygiene query patterns."""
        patterns = [
            "hygiene",
            "health check",
            "missing labels",
            "problems",
        ]
        for pattern in patterns:
            result = query_parser.parse(pattern)
            assert result.query_type == QueryType.HYGIENE, f"Failed for: {pattern}"

    def test_summary_patterns(self, query_parser):
        """Test summary query patterns."""
        patterns = [
            "summary",
            "overview",
            "all issues",
            "total",
            "count",
            "status report",
        ]
        for pattern in patterns:
            result = query_parser.parse(pattern)
            assert result.query_type == QueryType.SUMMARY, f"Failed for: {pattern}"

    def test_help_patterns(self, query_parser):
        """Test help query patterns."""
        patterns = [
            "help",
            "  help  ",
            "what can you do",
            "commands",
            "how do i",
        ]
        for pattern in patterns:
            result = query_parser.parse(pattern)
            assert result.query_type == QueryType.HELP, f"Failed for: {pattern}"

    def test_escalate_patterns(self, query_parser):
        """Test escalation patterns."""
        patterns = [
            "escalate",
            "talk to human",
            "talk to a human",
            "need person",
            "need a person",
            "human help",
        ]
        for pattern in patterns:
            result = query_parser.parse(pattern)
            assert result.query_type == QueryType.ESCALATE, f"Failed for: {pattern}"

    def test_intern_status_patterns(self, query_parser):
        """Test intern status patterns."""
        patterns = [
            "intern status",
            "intern progress",
            "intern update",
            "how is the intern",
        ]
        for pattern in patterns:
            result = query_parser.parse(pattern)
            assert result.query_type == QueryType.INTERN_STATUS, f"Failed for: {pattern}"


class TestQueryParserFilters:
    """Test filter extraction from queries."""

    def test_repo_filter_colon(self, query_parser):
        """Test repo:name filter extraction."""
        result = query_parser.parse("high priority repo:pulse")
        assert result.query_type == QueryType.HIGH_PRIORITY
        assert result.repo == "pulse"

    def test_repo_filter_space(self, query_parser):
        """Test repo name filter extraction."""
        result = query_parser.parse("unassigned repo pulse")
        assert result.query_type == QueryType.UNASSIGNED
        assert result.repo == "pulse"

    def test_assignee_filter(self, query_parser):
        """Test assignee filter extraction.

        Note: Uses 'assignee:alice' format instead of 'assigned to alice'
        because 'assigned' is itself a keyword that would match QueryType.ASSIGNED.
        """
        result = query_parser.parse("stale issues assignee:alice")
        assert result.query_type == QueryType.STALE
        assert result.assignee == "alice"

    def test_combined_filters(self, query_parser):
        """Test multiple filters in one query."""
        result = query_parser.parse("high priority repo:pulse assigned to bob")
        assert result.query_type == QueryType.HIGH_PRIORITY
        assert result.repo == "pulse"
        assert result.assignee == "bob"

    def test_intern_name_extraction(self, query_parser):
        """Test intern name extraction."""
        result = query_parser.parse("intern sara status")
        assert result.query_type == QueryType.INTERN_STATUS
        assert result.intern_name == "sara"


class TestQueryParserSensitiveTopics:
    """Test sensitive topic detection."""

    def test_sensitive_topics_trigger_escalation(self, query_parser):
        """Test that sensitive topics auto-escalate."""
        sensitive_queries = [
            "performance review for intern",
            "performance evaluation meeting",
            "evaluation of team member",
            "termination process",
            "harassment complaint",
            "salary information",
            "discussing compensation",
            "promotion decision",
        ]
        for query in sensitive_queries:
            result = query_parser.parse(query)
            assert result.query_type == QueryType.ESCALATE, f"Failed for: {query}"

    def test_false_positives_avoided(self, query_parser):
        """Test that word boundaries prevent false positives.

        The sensitive topics list now uses multi-word phrases like
        'performance review' instead of just 'performance', so technical
        uses shouldn't trigger escalation.
        """
        non_sensitive_queries = [
            "high-performance computing issues",  # no HR context
            "app performance is slow",  # performance without review/evaluation
            "firefighting the production issues",  # fire as part of firefighting
        ]
        for query in non_sensitive_queries:
            result = query_parser.parse(query)
            # These should NOT escalate
            assert result.query_type != QueryType.ESCALATE, f"False positive for: {query}"


class TestQueryParserEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_query_returns_help(self, query_parser):
        """Test that empty queries return help."""
        result = query_parser.parse("")
        assert result.query_type == QueryType.HELP

    def test_whitespace_only_returns_help(self, query_parser):
        """Test that whitespace-only queries return help."""
        result = query_parser.parse("   \t\n  ")
        assert result.query_type == QueryType.HELP

    def test_unknown_query(self, query_parser):
        """Test that unknown queries return unknown type."""
        result = query_parser.parse("xyzzy foo bar baz")
        assert result.query_type == QueryType.UNKNOWN
        assert result.confidence == 0.0

    def test_case_insensitive(self, query_parser):
        """Test that matching is case-insensitive."""
        result = query_parser.parse("HIGH PRIORITY")
        assert result.query_type == QueryType.HIGH_PRIORITY

    def test_very_long_input(self, query_parser):
        """Test handling of very long input."""
        long_text = "high priority " + "x" * 10000
        result = query_parser.parse(long_text)
        assert result.query_type == QueryType.HIGH_PRIORITY

    def test_unicode_input(self, query_parser):
        """Test handling of unicode characters."""
        result = query_parser.parse("high priority issues")
        assert result.query_type == QueryType.HIGH_PRIORITY

    def test_special_characters(self, query_parser):
        """Test handling of special characters."""
        result = query_parser.parse("high priority!!! @#$%")
        assert result.query_type == QueryType.HIGH_PRIORITY
