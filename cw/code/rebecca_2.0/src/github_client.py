"""
GitHub API client for fetching issues across repositories.

Protected by circuit breaker for resilience against GitHub API outages.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from github import Github
from github.GithubException import GithubException, RateLimitExceededException

from .bot.circuit_breaker import get_circuit_breaker, CircuitOpenError
from .utils import retry_with_backoff, wait_for_rate_limit_reset


@dataclass
class Issue:
    """Represents a GitHub issue."""
    repo: str
    number: int
    title: str
    assignee: Optional[str]
    labels: list[str]
    priority: Optional[str]
    status: Optional[str]
    issue_type: Optional[str]
    url: str
    updated: str
    created: str
    is_stale: bool = False


class GitHubClient:
    """Client for fetching issues from GitHub repositories."""

    # Label prefixes used by Cloud Warriors for categorization
    # Supports both formats: "PRIORITY: High" and "priority/high"
    # NOTE: Prefixes must be lowercase - matching is case-insensitive
    PRIORITY_PREFIXES = ("priority: ", "priority/", "priority:", "p:")
    STATUS_PREFIXES = ("status: ", "status/", "status:")
    TYPE_PREFIXES = ("type: ", "type/", "type:", "kind/")
    SKILL_PREFIXES = ("skill: ",)  # Complexity/skill level labels

    # Days without update before an issue is considered stale
    STALE_DAYS = 14

    # Rate limit safety threshold (stop if below this)
    RATE_LIMIT_THRESHOLD = 100

    def __init__(self, token: str, org: str = "cloudwarriors-ai", logger: logging.Logger = None):
        """
        Initialize the GitHub client.

        Args:
            token: GitHub personal access token
            org: GitHub organization name
            logger: Logger instance
        """
        if not token:
            raise ValueError("GitHub token is required")

        self.github = Github(token, timeout=30)
        self.org = org
        self.logger = logger or logging.getLogger("qa_agent")

        # Circuit breaker for GitHub API resilience
        self._circuit_breaker = get_circuit_breaker(
            name="github",
            failure_threshold=5,
            recovery_timeout=60,
            logger=self.logger,
        )

    def _extract_label_value(self, labels: list[str], prefixes: tuple) -> Optional[str]:
        """Extract label value matching given prefixes."""
        for label in labels:
            label_lower = label.lower()
            for prefix in prefixes:
                if label_lower.startswith(prefix):
                    return label[len(prefix):]
        return None

    def _is_stale(self, updated_at: datetime) -> bool:
        """Check if an issue is stale based on last update time."""
        days_since_update = (datetime.now() - updated_at.replace(tzinfo=None)).days
        return days_since_update > self.STALE_DAYS

    def _check_rate_limit(self) -> bool:
        """
        Check rate limit and wait if necessary.

        Returns:
            True if OK to proceed, False if should abort
        """
        try:
            rate_limit = self.github.get_rate_limit()
            remaining = rate_limit.rate.remaining

            if remaining < self.RATE_LIMIT_THRESHOLD:
                self.logger.warning(
                    f"Rate limit low: {remaining} remaining. Threshold: {self.RATE_LIMIT_THRESHOLD}"
                )
                if remaining == 0:
                    wait_for_rate_limit_reset(rate_limit.rate.reset, self.logger)
                return remaining > 0

            return True
        except Exception as e:
            self.logger.warning(f"Could not check rate limit: {e}")
            return True  # Proceed anyway

    def fetch_issues(self, repos: list[str]) -> list[Issue]:
        """
        Fetch all open issues from the specified repositories.

        Args:
            repos: List of repository names (without org prefix)

        Returns:
            List of Issue objects

        Raises:
            CircuitOpenError: If GitHub API circuit breaker is open
        """
        # Check circuit breaker before starting
        if not self._circuit_breaker.can_execute():
            raise CircuitOpenError("GitHub API circuit breaker is open. Service unavailable.")

        all_issues = []
        failed_repos = []

        for repo_name in repos:
            full_repo_name = f"{self.org}/{repo_name}"

            # Check rate limit before each repo
            self._check_rate_limit()

            try:
                issues = self._fetch_repo_issues(repo_name, full_repo_name)
                all_issues.extend(issues)
                self._circuit_breaker.record_success()
                self.logger.info(f"Fetched {len(issues)} issues from {repo_name}")

            except RateLimitExceededException:
                self.logger.error(f"Rate limit exceeded while fetching {repo_name}")
                self._circuit_breaker.record_failure()
                # Wait and retry once
                rate_limit = self.github.get_rate_limit()
                wait_for_rate_limit_reset(rate_limit.rate.reset, self.logger)
                try:
                    issues = self._fetch_repo_issues(repo_name, full_repo_name)
                    all_issues.extend(issues)
                    self._circuit_breaker.record_success()
                except Exception as e:
                    self.logger.error(f"Failed to fetch {repo_name} after rate limit wait: {e}")
                    self._circuit_breaker.record_failure()
                    failed_repos.append(repo_name)

            except GithubException as e:
                error_msg = e.data.get("message", str(e)) if hasattr(e, "data") else str(e)
                self.logger.error(f"GitHub API error for {full_repo_name}: {error_msg}")
                self._circuit_breaker.record_failure()
                failed_repos.append(repo_name)

            except Exception as e:
                self.logger.error(f"Unexpected error fetching {full_repo_name}: {e}")
                self._circuit_breaker.record_failure()
                failed_repos.append(repo_name)

        if failed_repos:
            self.logger.warning(f"Failed to fetch {len(failed_repos)} repos: {', '.join(failed_repos)}")

        return all_issues

    @retry_with_backoff(max_retries=2, base_delay=2.0, exceptions=(GithubException, ConnectionError))
    def _fetch_repo_issues(self, repo_name: str, full_repo_name: str) -> list[Issue]:
        """
        Fetch issues from a single repository with retry logic.

        Args:
            repo_name: Short repository name
            full_repo_name: Full org/repo name

        Returns:
            List of Issue objects for this repo
        """
        issues = []
        repo = self.github.get_repo(full_repo_name)

        for gh_issue in repo.get_issues(state="open"):
            # Skip pull requests (GitHub API returns them as issues)
            if gh_issue.pull_request is not None:
                continue

            labels = [label.name for label in gh_issue.labels]

            issue = Issue(
                repo=repo_name,
                number=gh_issue.number,
                title=gh_issue.title,
                assignee=gh_issue.assignee.login if gh_issue.assignee else None,
                labels=labels,
                priority=self._extract_label_value(labels, self.PRIORITY_PREFIXES),
                status=self._extract_label_value(labels, self.STATUS_PREFIXES),
                issue_type=self._extract_label_value(labels, self.TYPE_PREFIXES),
                url=gh_issue.html_url,
                updated=gh_issue.updated_at.strftime("%Y-%m-%d"),
                created=gh_issue.created_at.strftime("%Y-%m-%d"),
                is_stale=self._is_stale(gh_issue.updated_at),
            )
            issues.append(issue)

        return issues

    def get_rate_limit_status(self) -> dict:
        """Get current GitHub API rate limit status."""
        rate_limit = self.github.get_rate_limit()
        return {
            "remaining": rate_limit.rate.remaining,
            "limit": rate_limit.rate.limit,
            "reset_time": rate_limit.rate.reset.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # =========================================================================
    # GitHub Organization Management (for onboarding/offboarding)
    # =========================================================================

    def validate_github_user(self, username: str) -> dict:
        """
        Validate that a GitHub user exists and return profile info for confirmation.

        Args:
            username: GitHub username to validate

        Returns:
            Dict with exists flag and user details if found:
            - exists: True/False
            - login: GitHub username
            - name: User's display name (for confirmation)
            - avatar_url: Profile picture URL
            - error: Error message if not found
        """
        if not username or not username.strip():
            return {"exists": False, "error": "Username cannot be empty"}

        username = username.strip()

        # Check circuit breaker
        if not self._circuit_breaker.can_execute():
            return {"exists": False, "error": "GitHub API temporarily unavailable"}

        try:
            if not self._check_rate_limit():
                return {"exists": False, "error": "Rate limit exceeded"}

            user = self.github.get_user(username)
            self._circuit_breaker.record_success()

            return {
                "exists": True,
                "login": user.login,
                "name": user.name or user.login,  # Fallback to login if no name set
                "avatar_url": user.avatar_url,
                "profile_url": user.html_url,
                "bio": user.bio,
            }

        except GithubException as e:
            if e.status == 404:
                self.logger.info(f"GitHub user not found: {username}")
                # 404 is not a service failure, don't record as circuit failure
                return {"exists": False, "error": f"User '{username}' not found on GitHub"}
            error_msg = e.data.get("message", str(e)) if hasattr(e, "data") else str(e)
            self.logger.error(f"GitHub API error validating user {username}: {error_msg}")
            self._circuit_breaker.record_failure()
            return {"exists": False, "error": f"GitHub API error: {error_msg}"}

        except Exception as e:
            self.logger.error(f"Unexpected error validating GitHub user {username}: {e}")
            self._circuit_breaker.record_failure()
            return {"exists": False, "error": str(e)}

    def invite_to_org(self, username: str, role: str = "member") -> dict:
        """
        Invite a user to the GitHub organization.

        Requires admin:org scope on the GitHub token.

        Args:
            username: GitHub username to invite
            role: Role in org ('member' or 'admin'), defaults to 'member'

        Returns:
            Dict with success flag and details:
            - success: True/False
            - state: Invitation state ('pending', 'active')
            - error: Error message if failed
        """
        if not username or not username.strip():
            return {"success": False, "error": "Username cannot be empty"}

        username = username.strip()

        # Check circuit breaker
        if not self._circuit_breaker.can_execute():
            return {"success": False, "error": "GitHub API temporarily unavailable"}

        try:
            if not self._check_rate_limit():
                return {"success": False, "error": "Rate limit exceeded"}

            # Validate user exists first
            user_info = self.validate_github_user(username)
            if not user_info.get("exists"):
                return {"success": False, "error": user_info.get("error", "User not found")}

            # Get organization and invite user
            org = self.github.get_organization(self.org)
            user = self.github.get_user(username)

            # Check if already a member
            try:
                if org.has_in_members(user):
                    self.logger.info(f"User {username} is already a member of {self.org}")
                    return {
                        "success": True,
                        "state": "active",
                        "message": f"{username} is already a member of {self.org}"
                    }
            except GithubException:
                pass  # May not have permission to check membership

            # Invite user
            org.invite_user(user, role=role)
            self._circuit_breaker.record_success()
            self.logger.info(f"Invited {username} to {self.org} as {role}")

            return {
                "success": True,
                "state": "pending",
                "message": f"Invitation sent to {username}"
            }

        except GithubException as e:
            error_msg = e.data.get("message", str(e)) if hasattr(e, "data") else str(e)

            # Check for specific error conditions (not service failures)
            if e.status == 422 and "already a member" in error_msg.lower():
                return {
                    "success": True,
                    "state": "active",
                    "message": f"{username} is already a member"
                }
            if e.status == 403:
                self.logger.error(f"Permission denied inviting {username} - check org admin access")
                # 403 is auth issue, not service failure
                return {"success": False, "error": "Permission denied - check GitHub token has admin:org scope"}

            self.logger.error(f"GitHub API error inviting {username}: {error_msg}")
            self._circuit_breaker.record_failure()
            return {"success": False, "error": f"GitHub API error: {error_msg}"}

        except Exception as e:
            self.logger.error(f"Unexpected error inviting {username} to org: {e}")
            self._circuit_breaker.record_failure()
            return {"success": False, "error": str(e)}

    def remove_from_org(self, username: str) -> dict:
        """
        Remove a user from the GitHub organization.

        Requires admin:org scope on the GitHub token.

        Args:
            username: GitHub username to remove

        Returns:
            Dict with success flag and details:
            - success: True/False
            - error: Error message if failed
        """
        if not username or not username.strip():
            return {"success": False, "error": "Username cannot be empty"}

        username = username.strip()

        # Check circuit breaker
        if not self._circuit_breaker.can_execute():
            return {"success": False, "error": "GitHub API temporarily unavailable"}

        try:
            if not self._check_rate_limit():
                return {"success": False, "error": "Rate limit exceeded"}

            org = self.github.get_organization(self.org)
            user = self.github.get_user(username)

            # Check if user is a member
            try:
                if not org.has_in_members(user):
                    self.logger.info(f"User {username} is not a member of {self.org}")
                    return {
                        "success": True,
                        "message": f"{username} is not a member of {self.org} (already removed)"
                    }
            except GithubException:
                pass  # May not have permission to check, try removal anyway

            # Remove user
            org.remove_from_members(user)
            self._circuit_breaker.record_success()
            self.logger.info(f"Removed {username} from {self.org}")

            return {
                "success": True,
                "message": f"{username} removed from {self.org}"
            }

        except GithubException as e:
            error_msg = e.data.get("message", str(e)) if hasattr(e, "data") else str(e)

            if e.status == 404:
                # 404 means user not found - not a service failure
                return {
                    "success": True,
                    "message": f"{username} is not a member (already removed)"
                }
            if e.status == 403:
                self.logger.error(f"Permission denied removing {username} - check org admin access")
                # 403 is auth issue, not service failure
                return {"success": False, "error": "Permission denied - check GitHub token has admin:org scope"}

            self.logger.error(f"GitHub API error removing {username}: {error_msg}")
            self._circuit_breaker.record_failure()
            return {"success": False, "error": f"GitHub API error: {error_msg}"}

        except Exception as e:
            self.logger.error(f"Unexpected error removing {username} from org: {e}")
            self._circuit_breaker.record_failure()
            return {"success": False, "error": str(e)}

    def get_circuit_status(self) -> dict:
        """Get circuit breaker status for health checks."""
        return self._circuit_breaker.get_status()

    def get_org_membership(self, username: str) -> dict:
        """
        Check a user's membership status in the organization.

        Args:
            username: GitHub username to check

        Returns:
            Dict with membership details:
            - is_member: True/False
            - role: 'member', 'admin', or None
            - state: 'active', 'pending', or None
        """
        if not username or not username.strip():
            return {"is_member": False, "error": "Username cannot be empty"}

        username = username.strip()

        try:
            org = self.github.get_organization(self.org)
            user = self.github.get_user(username)

            # Check membership
            try:
                membership = org.get_members_membership(user)
                return {
                    "is_member": True,
                    "role": membership.role,
                    "state": membership.state,
                }
            except GithubException as e:
                if e.status == 404:
                    return {"is_member": False, "role": None, "state": None}
                raise

        except GithubException as e:
            error_msg = e.data.get("message", str(e)) if hasattr(e, "data") else str(e)
            self.logger.warning(f"Could not check membership for {username}: {error_msg}")
            return {"is_member": False, "error": error_msg}

        except Exception as e:
            self.logger.error(f"Unexpected error checking membership for {username}: {e}")
            return {"is_member": False, "error": str(e)}
