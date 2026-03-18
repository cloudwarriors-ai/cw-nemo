"""
Tests for GitHub organization management.

Tests the new methods for:
- validate_github_user
- invite_to_org
- remove_from_org
- get_org_membership
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from github.GithubException import GithubException

from src.github_client import GitHubClient


@pytest.fixture
def mock_github():
    """Create a mock PyGithub instance."""
    with patch("src.github_client.Github") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        # Mock rate limit
        mock_rate = Mock()
        mock_rate.remaining = 1000
        mock_rate.limit = 5000
        mock_rate.reset = Mock()
        mock_rate.reset.strftime = Mock(return_value="2026-01-13 00:00:00")
        mock_instance.get_rate_limit.return_value.rate = mock_rate

        yield mock_instance


@pytest.fixture
def github_client(mock_github):
    """Create a GitHubClient with mocked PyGithub."""
    client = GitHubClient(
        token="fake-token",
        org="cloudwarriors-ai"
    )
    return client


class TestValidateGithubUser:
    """Tests for validate_github_user method."""

    def test_valid_user(self, github_client, mock_github):
        """Test validating an existing user."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_user.name = "Test User"
        mock_user.avatar_url = "https://avatars.githubusercontent.com/u/123"
        mock_user.html_url = "https://github.com/testuser"
        mock_user.bio = "A test user"
        mock_github.get_user.return_value = mock_user

        result = github_client.validate_github_user("testuser")

        assert result["exists"] is True
        assert result["login"] == "testuser"
        assert result["name"] == "Test User"
        assert "avatar_url" in result
        assert "profile_url" in result

    def test_user_not_found(self, github_client, mock_github):
        """Test validating a non-existent user."""
        mock_github.get_user.side_effect = GithubException(
            status=404,
            data={"message": "Not Found"}
        )

        result = github_client.validate_github_user("nonexistent")

        assert result["exists"] is False
        assert "not found" in result["error"].lower()

    def test_empty_username(self, github_client):
        """Test validating empty username."""
        result = github_client.validate_github_user("")

        assert result["exists"] is False
        assert "empty" in result["error"].lower()

    def test_whitespace_username(self, github_client):
        """Test username is stripped of whitespace."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_user.name = "Test User"
        mock_user.avatar_url = "https://example.com/avatar"
        mock_user.html_url = "https://github.com/testuser"
        mock_user.bio = None

        with patch.object(github_client.github, "get_user", return_value=mock_user):
            result = github_client.validate_github_user("  testuser  ")

        assert result["exists"] is True
        assert result["login"] == "testuser"


class TestInviteToOrg:
    """Tests for invite_to_org method."""

    def test_invite_new_user(self, github_client, mock_github):
        """Test inviting a new user to org."""
        mock_user = Mock()
        mock_user.login = "newuser"
        mock_user.name = "New User"
        mock_user.avatar_url = "https://example.com/avatar"
        mock_user.html_url = "https://github.com/newuser"
        mock_user.bio = None
        mock_github.get_user.return_value = mock_user

        mock_org = Mock()
        mock_org.has_in_members.return_value = False
        mock_org.invite_user.return_value = None
        mock_github.get_organization.return_value = mock_org

        result = github_client.invite_to_org("newuser")

        assert result["success"] is True
        assert result["state"] == "pending"
        mock_org.invite_user.assert_called_once()

    def test_invite_existing_member(self, github_client, mock_github):
        """Test inviting an existing member."""
        mock_user = Mock()
        mock_user.login = "existinguser"
        mock_user.name = "Existing User"
        mock_user.avatar_url = "https://example.com/avatar"
        mock_user.html_url = "https://github.com/existinguser"
        mock_user.bio = None
        mock_github.get_user.return_value = mock_user

        mock_org = Mock()
        mock_org.has_in_members.return_value = True
        mock_github.get_organization.return_value = mock_org

        result = github_client.invite_to_org("existinguser")

        assert result["success"] is True
        assert result["state"] == "active"
        assert "already" in result["message"].lower()

    def test_invite_nonexistent_user(self, github_client, mock_github):
        """Test inviting a non-existent user."""
        mock_github.get_user.side_effect = GithubException(
            status=404,
            data={"message": "Not Found"}
        )

        result = github_client.invite_to_org("nonexistent")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_invite_permission_denied(self, github_client, mock_github):
        """Test invite when lacking permissions."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_user.name = "Test User"
        mock_user.avatar_url = "https://example.com/avatar"
        mock_user.html_url = "https://github.com/testuser"
        mock_user.bio = None
        mock_github.get_user.return_value = mock_user

        mock_org = Mock()
        mock_org.has_in_members.return_value = False
        mock_org.invite_user.side_effect = GithubException(
            status=403,
            data={"message": "Must have admin rights"}
        )
        mock_github.get_organization.return_value = mock_org

        result = github_client.invite_to_org("testuser")

        assert result["success"] is False
        assert "permission" in result["error"].lower()

    def test_invite_empty_username(self, github_client):
        """Test invite with empty username."""
        result = github_client.invite_to_org("")

        assert result["success"] is False
        assert "empty" in result["error"].lower()


class TestRemoveFromOrg:
    """Tests for remove_from_org method."""

    def test_remove_member(self, github_client, mock_github):
        """Test removing an existing member."""
        mock_user = Mock()
        mock_github.get_user.return_value = mock_user

        mock_org = Mock()
        mock_org.has_in_members.return_value = True
        mock_org.remove_from_members.return_value = None
        mock_github.get_organization.return_value = mock_org

        result = github_client.remove_from_org("testuser")

        assert result["success"] is True
        mock_org.remove_from_members.assert_called_once_with(mock_user)

    def test_remove_non_member(self, github_client, mock_github):
        """Test removing a non-member."""
        mock_user = Mock()
        mock_github.get_user.return_value = mock_user

        mock_org = Mock()
        mock_org.has_in_members.return_value = False
        mock_github.get_organization.return_value = mock_org

        result = github_client.remove_from_org("nonmember")

        assert result["success"] is True
        assert "not a member" in result["message"].lower()

    def test_remove_permission_denied(self, github_client, mock_github):
        """Test remove when lacking permissions."""
        mock_user = Mock()
        mock_github.get_user.return_value = mock_user

        mock_org = Mock()
        mock_org.has_in_members.return_value = True
        mock_org.remove_from_members.side_effect = GithubException(
            status=403,
            data={"message": "Must have admin rights"}
        )
        mock_github.get_organization.return_value = mock_org

        result = github_client.remove_from_org("testuser")

        assert result["success"] is False
        assert "permission" in result["error"].lower()

    def test_remove_empty_username(self, github_client):
        """Test remove with empty username."""
        result = github_client.remove_from_org("")

        assert result["success"] is False
        assert "empty" in result["error"].lower()


class TestGetOrgMembership:
    """Tests for get_org_membership method."""

    def test_active_member(self, github_client, mock_github):
        """Test checking active member."""
        mock_user = Mock()
        mock_github.get_user.return_value = mock_user

        mock_membership = Mock()
        mock_membership.role = "member"
        mock_membership.state = "active"

        mock_org = Mock()
        mock_org.get_members_membership.return_value = mock_membership
        mock_github.get_organization.return_value = mock_org

        result = github_client.get_org_membership("testuser")

        assert result["is_member"] is True
        assert result["role"] == "member"
        assert result["state"] == "active"

    def test_non_member(self, github_client, mock_github):
        """Test checking non-member."""
        mock_user = Mock()
        mock_github.get_user.return_value = mock_user

        mock_org = Mock()
        mock_org.get_members_membership.side_effect = GithubException(
            status=404,
            data={"message": "Not Found"}
        )
        mock_github.get_organization.return_value = mock_org

        result = github_client.get_org_membership("nonmember")

        assert result["is_member"] is False

    def test_empty_username(self, github_client):
        """Test checking empty username."""
        result = github_client.get_org_membership("")

        assert result["is_member"] is False
        assert "empty" in result["error"].lower()


class TestRateLimitHandling:
    """Tests for rate limit handling."""

    def test_rate_limit_is_checked(self, github_client, mock_github):
        """Test rate limit is checked (and logged) during invite."""
        # Set low rate limit - the client checks rate limits before operations
        # but uses fail-open design (proceeds if check fails)
        mock_rate = Mock()
        mock_rate.remaining = 50  # Below threshold but > 0
        mock_rate.limit = 5000
        mock_rate.reset = Mock()
        mock_rate.reset.strftime = Mock(return_value="2026-01-13 00:00:00")
        mock_github.get_rate_limit.return_value.rate = mock_rate

        mock_user = Mock()
        mock_user.login = "testuser"
        mock_user.name = "Test User"
        mock_user.avatar_url = "https://example.com/avatar"
        mock_user.html_url = "https://github.com/testuser"
        mock_user.bio = None
        mock_github.get_user.return_value = mock_user

        mock_org = Mock()
        mock_org.has_in_members.return_value = False
        mock_org.invite_user.return_value = None
        mock_github.get_organization.return_value = mock_org

        result = github_client.invite_to_org("testuser")

        # Should succeed (rate limit check is advisory, not blocking)
        assert result["success"] is True
        # Rate limit was checked
        mock_github.get_rate_limit.assert_called()
