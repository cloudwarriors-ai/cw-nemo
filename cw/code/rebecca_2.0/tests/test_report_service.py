"""
Tests for ReportService.

Tests weekly report generation and formatting for Zoom.
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.bot.services.report_service import ReportService, WeeklyReport


class TestWeeklyReport:
    """Tests for WeeklyReport dataclass."""

    def test_to_dict_with_valid_data(self):
        """Test WeeklyReport serialization with valid data."""
        report = WeeklyReport(
            generated_at=datetime(2024, 1, 15, 9, 0, 0),
            total_issues=50,
            high_priority=10,
            unassigned=5,
            stale=3,
            by_repo={"pulse": 20, "macd": 30},
            cache_age_seconds=120.5,
            has_valid_data=True,
        )

        result = report.to_dict()

        assert result["generated_at"] == "2024-01-15T09:00:00"
        assert result["total_issues"] == 50
        assert result["high_priority"] == 10
        assert result["unassigned"] == 5
        assert result["stale"] == 3
        assert result["by_repo"] == {"pulse": 20, "macd": 30}
        assert result["cache_age_seconds"] == 120.5
        assert result["has_valid_data"] is True
        assert result["error"] is None

    def test_to_dict_with_error(self):
        """Test WeeklyReport serialization with error state."""
        report = WeeklyReport(
            generated_at=datetime(2024, 1, 15, 9, 0, 0),
            total_issues=0,
            high_priority=0,
            unassigned=0,
            stale=0,
            has_valid_data=False,
            error="GitHub API unavailable",
        )

        result = report.to_dict()

        assert result["has_valid_data"] is False
        assert result["error"] == "GitHub API unavailable"
        assert result["total_issues"] == 0


class TestReportService:
    """Tests for ReportService."""

    @pytest.fixture
    def mock_issue_cache(self):
        """Create a mock IssueCache."""
        cache = MagicMock()
        cache.has_data = True
        cache.get_stats.return_value = {
            "total": 50,
            "high_priority": 10,
            "unassigned": 5,
            "stale": 3,
            "by_repo": {"pulse": 20, "macd": 30},
            "cache_age_seconds": 120.5,
        }
        return cache

    @pytest.fixture
    def report_service(self, mock_issue_cache):
        """Create a ReportService instance."""
        return ReportService(issue_cache=mock_issue_cache)

    def test_generate_weekly_report_success(self, report_service, mock_issue_cache):
        """Test successful weekly report generation."""
        report = report_service.generate_weekly_report()

        assert report.has_valid_data is True
        assert report.total_issues == 50
        assert report.high_priority == 10
        assert report.unassigned == 5
        assert report.stale == 3
        assert report.by_repo == {"pulse": 20, "macd": 30}
        assert report.error is None
        mock_issue_cache.get_stats.assert_called_once()

    def test_generate_weekly_report_empty_cache(self, mock_issue_cache):
        """Test report generation when cache is empty."""
        mock_issue_cache.has_data = False
        service = ReportService(issue_cache=mock_issue_cache)

        report = service.generate_weekly_report()

        assert report.has_valid_data is False
        assert report.error == "GitHub data unavailable - cache empty"
        assert report.total_issues == 0

    def test_generate_weekly_report_exception(self, mock_issue_cache):
        """Test report generation handles exceptions gracefully."""
        mock_issue_cache.has_data = True
        mock_issue_cache.get_stats.side_effect = Exception("Database error")
        service = ReportService(issue_cache=mock_issue_cache)

        report = service.generate_weekly_report()

        assert report.has_valid_data is False
        assert "Database error" in report.error
        assert report.total_issues == 0

    def test_format_for_zoom_valid_report(self, report_service):
        """Test formatting a valid report for Zoom."""
        report = WeeklyReport(
            generated_at=datetime(2024, 1, 15, 9, 0, 0),
            total_issues=50,
            high_priority=10,
            unassigned=5,
            stale=3,
            by_repo={"pulse": 20, "macd": 30},
            cache_age_seconds=120.5,
            has_valid_data=True,
        )

        formatted = report_service.format_for_zoom(report)

        assert "Weekly Issue Report - January 15, 2024" in formatted
        assert "Total Open Issues: 50" in formatted
        assert "High Priority: 10" in formatted
        assert "Unassigned: 5" in formatted
        assert "Stale (14+ days): 3" in formatted
        assert "macd: 30" in formatted
        assert "pulse: 20" in formatted
        # Cache age < 1 hour, should not show warning
        assert "hours old" not in formatted

    def test_format_for_zoom_stale_cache(self, report_service):
        """Test format shows warning when cache is stale."""
        report = WeeklyReport(
            generated_at=datetime(2024, 1, 15, 9, 0, 0),
            total_issues=50,
            high_priority=10,
            unassigned=5,
            stale=3,
            cache_age_seconds=7200,  # 2 hours
            has_valid_data=True,
        )

        formatted = report_service.format_for_zoom(report)

        assert "2.0 hours old" in formatted

    def test_format_for_zoom_invalid_report(self, report_service):
        """Test formatting an invalid report shows error message."""
        report = WeeklyReport(
            generated_at=datetime(2024, 1, 15, 9, 0, 0),
            total_issues=0,
            high_priority=0,
            unassigned=0,
            stale=0,
            has_valid_data=False,
            error="API unavailable",
        )

        formatted = report_service.format_for_zoom(report)

        assert "Weekly Issue Report - January 15, 2024" in formatted
        assert "Unable to generate report: API unavailable" in formatted
        assert "Please check GitHub connectivity" in formatted

    def test_format_for_zoom_no_repos(self, report_service):
        """Test formatting when by_repo is empty."""
        report = WeeklyReport(
            generated_at=datetime(2024, 1, 15, 9, 0, 0),
            total_issues=10,
            high_priority=2,
            unassigned=1,
            stale=0,
            by_repo={},
            has_valid_data=True,
        )

        formatted = report_service.format_for_zoom(report)

        assert "By Repository:" not in formatted
        assert "Total Open Issues: 10" in formatted

    def test_format_includes_help_text(self, report_service):
        """Test that formatted report includes help text."""
        report = WeeklyReport(
            generated_at=datetime(2024, 1, 15, 9, 0, 0),
            total_issues=50,
            high_priority=10,
            unassigned=5,
            stale=3,
            has_valid_data=True,
        )

        formatted = report_service.format_for_zoom(report)

        assert "show high priority issues" in formatted
        assert "show unassigned" in formatted
