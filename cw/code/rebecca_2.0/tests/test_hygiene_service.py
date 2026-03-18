"""
Tests for HygieneService.

Tests issue hygiene checking and alert formatting for Zoom.
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from src.bot.services.hygiene_service import HygieneService, HygieneReport, HygieneIssue
from src.github_client import Issue


class TestHygieneReport:
    """Tests for HygieneReport dataclass."""

    def test_to_dict_with_valid_data(self):
        """Test HygieneReport serialization."""
        report = HygieneReport(
            generated_at=datetime(2024, 1, 15, 8, 0, 0),
            total_issues_checked=50,
            issues_needing_attention=10,
            missing_labels=[HygieneIssue("repo1", 1, "Test", "url", ["no labels"])],
            missing_priority=[HygieneIssue("repo1", 2, "Test2", "url", ["no priority"])],
            missing_assignee=[],
            stale_issues=[],
            has_valid_data=True,
        )

        result = report.to_dict()

        assert result["generated_at"] == "2024-01-15T08:00:00"
        assert result["total_issues_checked"] == 50
        assert result["issues_needing_attention"] == 10
        assert result["missing_labels_count"] == 1
        assert result["missing_priority_count"] == 1
        assert result["missing_assignee_count"] == 0
        assert result["stale_issues_count"] == 0
        assert result["has_valid_data"] is True


class TestHygieneService:
    """Tests for HygieneService."""

    @pytest.fixture
    def mock_issue_cache(self):
        """Create a mock IssueCache with sample issues."""
        cache = MagicMock()
        cache.has_data = True

        # Create sample issues with various hygiene problems
        issues = [
            Issue(
                repo="pulse",
                number=1,
                title="Well-labeled issue",
                assignee="alice",
                labels=["priority/high", "type/bug"],
                priority="high",
                status=None,
                issue_type="bug",
                url="https://github.com/org/pulse/issues/1",
                updated="2024-01-10",
                created="2024-01-01",
                is_stale=False,
            ),
            Issue(
                repo="pulse",
                number=2,
                title="Missing priority issue",
                assignee="bob",
                labels=["type/feature"],
                priority=None,
                status=None,
                issue_type="feature",
                url="https://github.com/org/pulse/issues/2",
                updated="2024-01-10",
                created="2024-01-01",
                is_stale=False,
            ),
            Issue(
                repo="macd",
                number=3,
                title="Unassigned issue",
                assignee=None,
                labels=["priority/medium"],
                priority="medium",
                status=None,
                issue_type=None,
                url="https://github.com/org/macd/issues/3",
                updated="2024-01-10",
                created="2024-01-01",
                is_stale=False,
            ),
            Issue(
                repo="macd",
                number=4,
                title="Stale and unassigned",
                assignee=None,
                labels=[],
                priority=None,
                status=None,
                issue_type=None,
                url="https://github.com/org/macd/issues/4",
                updated="2023-12-01",
                created="2023-11-01",
                is_stale=True,
            ),
        ]
        cache.get_issues.return_value = issues
        return cache

    @pytest.fixture
    def hygiene_service(self, mock_issue_cache):
        """Create a HygieneService instance."""
        return HygieneService(issue_cache=mock_issue_cache)

    def test_check_hygiene_success(self, hygiene_service, mock_issue_cache):
        """Test successful hygiene check."""
        report = hygiene_service.check_hygiene()

        assert report.has_valid_data is True
        assert report.total_issues_checked == 4
        # Issues 2, 3, 4 have problems
        assert report.issues_needing_attention == 3
        # Issue 2 and 4 missing priority
        assert len(report.missing_priority) == 2
        # Issues 3 and 4 are unassigned
        assert len(report.missing_assignee) == 2
        # Issue 4 is stale
        assert len(report.stale_issues) == 1
        # Issue 4 has no labels
        assert len(report.missing_labels) == 1
        mock_issue_cache.get_issues.assert_called_once()

    def test_check_hygiene_empty_cache(self, mock_issue_cache):
        """Test hygiene check when cache is empty."""
        mock_issue_cache.has_data = False
        service = HygieneService(issue_cache=mock_issue_cache)

        report = service.check_hygiene()

        assert report.has_valid_data is False
        assert report.error == "GitHub data unavailable - cache empty"
        assert report.total_issues_checked == 0

    def test_check_hygiene_exception(self, mock_issue_cache):
        """Test hygiene check handles exceptions gracefully."""
        mock_issue_cache.has_data = True
        mock_issue_cache.get_issues.side_effect = Exception("Database error")
        service = HygieneService(issue_cache=mock_issue_cache)

        report = service.check_hygiene()

        assert report.has_valid_data is False
        assert "Database error" in report.error
        assert report.total_issues_checked == 0

    def test_check_hygiene_all_clean(self, mock_issue_cache):
        """Test hygiene check when all issues are clean."""
        mock_issue_cache.get_issues.return_value = [
            Issue(
                repo="pulse",
                number=1,
                title="Perfect issue",
                assignee="alice",
                labels=["priority/high", "type/bug"],
                priority="high",
                status=None,
                issue_type="bug",
                url="https://github.com/org/pulse/issues/1",
                updated="2024-01-10",
                created="2024-01-01",
                is_stale=False,
            ),
        ]
        service = HygieneService(issue_cache=mock_issue_cache)

        report = service.check_hygiene()

        assert report.has_valid_data is True
        assert report.issues_needing_attention == 0
        assert len(report.missing_labels) == 0
        assert len(report.missing_priority) == 0
        assert len(report.missing_assignee) == 0
        assert len(report.stale_issues) == 0

    def test_format_for_zoom_with_issues(self, hygiene_service):
        """Test formatting a report with issues for Zoom."""
        report = HygieneReport(
            generated_at=datetime(2024, 1, 15, 8, 0, 0),
            total_issues_checked=50,
            issues_needing_attention=10,
            missing_priority=[
                HygieneIssue("pulse", 1, "Missing prio", "url1", ["no priority"]),
                HygieneIssue("pulse", 2, "Also missing", "url2", ["no priority"]),
            ],
            missing_assignee=[
                HygieneIssue("macd", 3, "Unassigned", "url3", ["unassigned"]),
            ],
            stale_issues=[
                HygieneIssue("hermes", 4, "Old issue", "url4", ["stale"]),
            ],
            missing_labels=[],
            has_valid_data=True,
        )

        formatted = hygiene_service.format_for_zoom(report)

        assert "Issue Hygiene Report - January 15, 2024" in formatted
        assert "Checked 50 issues, 10 need attention" in formatted
        assert "Missing Priority (2):" in formatted
        assert "pulse#1: Missing prio" in formatted
        assert "Unassigned (1):" in formatted
        assert "macd#3: Unassigned" in formatted
        assert "Stale Issues (1):" in formatted
        assert "hermes#4: Old issue" in formatted

    def test_format_for_zoom_no_issues(self, hygiene_service):
        """Test formatting when no issues need attention."""
        report = HygieneReport(
            generated_at=datetime(2024, 1, 15, 8, 0, 0),
            total_issues_checked=50,
            issues_needing_attention=0,
            has_valid_data=True,
        )

        formatted = hygiene_service.format_for_zoom(report)

        assert "All issues are properly labeled and assigned!" in formatted

    def test_format_for_zoom_invalid_report(self, hygiene_service):
        """Test formatting an invalid report shows error message."""
        report = HygieneReport(
            generated_at=datetime(2024, 1, 15, 8, 0, 0),
            total_issues_checked=0,
            issues_needing_attention=0,
            has_valid_data=False,
            error="API unavailable",
        )

        formatted = hygiene_service.format_for_zoom(report)

        assert "Unable to generate report: API unavailable" in formatted

    def test_format_for_zoom_truncates_long_lists(self, hygiene_service):
        """Test that formatting truncates long issue lists."""
        many_issues = [
            HygieneIssue(f"repo{i}", i, f"Issue {i}", f"url{i}", ["no priority"])
            for i in range(10)
        ]
        report = HygieneReport(
            generated_at=datetime(2024, 1, 15, 8, 0, 0),
            total_issues_checked=100,
            issues_needing_attention=10,
            missing_priority=many_issues,
            has_valid_data=True,
        )

        formatted = hygiene_service.format_for_zoom(report, max_per_category=5)

        assert "Missing Priority (10):" in formatted
        assert "... and 5 more" in formatted
        # Should only show 5 issues
        assert "Issue 4" in formatted
        assert "Issue 5" not in formatted or "... and 5 more" in formatted
