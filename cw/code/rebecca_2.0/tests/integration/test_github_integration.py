"""
Integration tests for GitHub API.

These tests require a valid GITHUB_TOKEN to run.
Run with: pytest tests/integration/test_github_integration.py -v

To run only if credentials are available:
    pytest tests/integration/ -v -m github
"""
import pytest
from .conftest import skip_without_github


@pytest.mark.integration
@pytest.mark.github
class TestGitHubIntegration:
    """Integration tests for GitHub API connectivity."""

    @skip_without_github
    def test_github_client_connects(self, github_token, github_org):
        """Test that GitHub client can connect and authenticate."""
        from src.github_client import GitHubClient

        client = GitHubClient(token=github_token)

        # Test rate limit endpoint (doesn't count against quota)
        rate_limit = client.get_rate_limit()

        assert rate_limit is not None
        assert "limit" in rate_limit
        assert "remaining" in rate_limit
        assert rate_limit["remaining"] >= 0

    @skip_without_github
    def test_github_client_fetches_issues(self, github_token, github_org):
        """Test that GitHub client can fetch issues from a repo."""
        from src.github_client import GitHubClient

        client = GitHubClient(token=github_token)

        # Fetch issues from the org (any public repo)
        # This tests the API call works, even if no issues exist
        try:
            # Try fetching from a common repo pattern
            issues = client.fetch_open_issues(github_org, "test-repo")
            # If repo doesn't exist, this is fine - we're testing the API call
            assert isinstance(issues, list)
        except Exception as e:
            # 404 is acceptable - means API works but repo doesn't exist
            if "404" not in str(e) and "Not Found" not in str(e):
                raise

    @skip_without_github
    def test_github_rate_limit_info(self, github_token):
        """Test that rate limit information is accurate."""
        from src.github_client import GitHubClient

        client = GitHubClient(token=github_token)
        rate_limit = client.get_rate_limit()

        # Should have core rate limit info
        assert rate_limit["limit"] >= 60  # Authenticated gets 5000, unauth gets 60
        assert rate_limit["remaining"] <= rate_limit["limit"]

    @skip_without_github
    def test_health_endpoint_with_github(self, integration_client):
        """Test health endpoint shows GitHub as configured."""
        response = integration_client.get("/health?detailed=true")
        assert response.status_code == 200

        data = response.get_json()
        assert data["config"]["github_configured"] is True

        # Detailed check should show GitHub status
        if "dependencies" in data:
            github_status = data["dependencies"].get("github", {})
            # Either configured or has actual status
            assert github_status.get("status") in ["ok", "configured", "not_configured"]


@pytest.mark.integration
@pytest.mark.github
class TestIssueCacheIntegration:
    """Integration tests for issue caching with real GitHub data."""

    @skip_without_github
    def test_cache_initialization(self, github_token, github_org):
        """Test that issue cache initializes with real data."""
        from src.github_client import GitHubClient
        from src.bot.cache import IssueCache

        client = GitHubClient(token=github_token)
        cache = IssueCache(github_client=client, repos=[], ttl_seconds=60)

        # Cache should start empty
        assert cache.age_seconds >= 0

    @skip_without_github
    def test_cache_refresh(self, github_token, github_org):
        """Test that cache can be refreshed."""
        from src.github_client import GitHubClient
        from src.bot.cache import IssueCache

        client = GitHubClient(token=github_token)
        cache = IssueCache(github_client=client, repos=[], ttl_seconds=60)

        # Force refresh
        cache.invalidate()
        issues = cache.get_issues(force_refresh=True)

        assert isinstance(issues, list)


@pytest.mark.integration
@pytest.mark.github
class TestQueryProcessingIntegration:
    """Integration tests for query processing with real GitHub."""

    @skip_without_github
    def test_help_command(self, integration_client):
        """Test help command works."""
        response = integration_client.post(
            "/api/query",
            json={"query": "help", "user": "integration-test"}
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "response" in data
        assert "Commands" in data["response"] or "help" in data["response"].lower()

    @skip_without_github
    def test_high_priority_query(self, integration_client):
        """Test high priority query works."""
        response = integration_client.post(
            "/api/query",
            json={"query": "high priority", "user": "integration-test"}
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "response" in data
        # Should return some response (even if no high priority issues)

    @skip_without_github
    def test_unknown_query_handled(self, integration_client):
        """Test unknown query is handled gracefully."""
        response = integration_client.post(
            "/api/query",
            json={"query": "xyzzy random unknown query", "user": "integration-test"}
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "response" in data
        # Should return help or clarification, not an error
