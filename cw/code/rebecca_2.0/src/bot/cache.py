"""
Caching layer for GitHub issues with SQLite persistence.

Stores issues in SQLite database for instant queries. Refresh is manual only
to avoid blocking requests during background fetches.
"""
import json
import logging
import sqlite3
import time
from datetime import datetime
from threading import RLock, Thread
from typing import Optional

from ..github_client import GitHubClient, Issue
from .models import IssueFilter


class IssueCache:
    """
    SQLite-backed cache for GitHub issues.

    Issues are stored in the database and returned instantly.
    Refresh is triggered manually via refresh() or on first request if empty.
    """

    def __init__(
        self,
        github_client: GitHubClient,
        repos: list[str],
        db_path: str = "data/state.db",
        ttl_seconds: int = 60,  # Kept for API compatibility, not used for auto-refresh
        logger: logging.Logger = None
    ):
        """
        Initialize the issue cache.

        Args:
            github_client: GitHubClient instance for fetching issues
            repos: List of repository names to fetch from
            db_path: Path to SQLite database
            ttl_seconds: Not used (kept for API compatibility)
            logger: Logger instance
        """
        self.github_client = github_client
        self.repos = repos
        self.db_path = db_path
        self.ttl = ttl_seconds  # Kept for API compat
        self.logger = logger or logging.getLogger("qa_agent")

        self._lock = RLock()
        self._is_fetching = False
        self._last_refresh: Optional[float] = None

        # Load last refresh time from metadata
        self._load_metadata()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _load_metadata(self) -> None:
        """Load cache metadata from database."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM cache_metadata WHERE key = 'last_refresh'"
            )
            row = cursor.fetchone()
            if row:
                self._last_refresh = float(row["value"])
            conn.close()
        except Exception as e:
            self.logger.warning(f"Failed to load cache metadata: {e}")

    def _save_metadata(self) -> None:
        """Save cache metadata to database."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO cache_metadata (key, value, updated_at)
                VALUES ('last_refresh', ?, datetime('now'))
            """, (str(time.time()),))
            conn.commit()
            conn.close()
            self._last_refresh = time.time()
        except Exception as e:
            self.logger.warning(f"Failed to save cache metadata: {e}")

    @property
    def is_stale(self) -> bool:
        """Check if cache data exists. Always returns False if data exists."""
        return not self.has_data

    @property
    def has_data(self) -> bool:
        """Check if we have cached data."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM issue_cache")
            count = cursor.fetchone()[0]
            conn.close()
            return count > 0
        except Exception:
            return False

    @property
    def age_seconds(self) -> float:
        """Get age of cached data in seconds."""
        if self._last_refresh is None:
            return float('inf')
        return time.time() - self._last_refresh

    @property
    def issue_count(self) -> int:
        """Get count of cached issues."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM issue_cache")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def get_issues(self, force_refresh: bool = False) -> list[Issue]:
        """
        Get cached issues from database.

        If cache is empty and not currently refreshing, triggers an initial load.
        Returns instantly with whatever data is available.

        Args:
            force_refresh: If True, triggers a background refresh

        Returns:
            List of Issue objects from cache
        """
        # If force_refresh requested, start background refresh
        if force_refresh:
            self._start_background_refresh()

        # Check if we need initial load
        if not self.has_data and not self._is_fetching:
            # Do initial load synchronously (only happens once)
            self.logger.info("Cache empty, performing initial load...")
            self._refresh_sync()

        return self._load_from_db()

    def _load_from_db(
        self,
        issue_filter: Optional[IssueFilter] = None,
        # Legacy parameters for backwards compatibility
        repo: str = None,
        assignee: str = None,
        priority: str = None,
        stale_only: bool = False,
        unassigned_only: bool = False,
        assigned_only: bool = False,
        hygiene_issues_only: bool = False
    ) -> list[Issue]:
        """
        Load issues from SQLite with optional filters.

        Args:
            issue_filter: IssueFilter object with filter parameters (preferred)
            repo: Filter by repository name (legacy)
            assignee: Filter by assignee (legacy)
            priority: Filter by priority (legacy)
            stale_only: Only return stale issues (legacy)
            unassigned_only: Only return unassigned issues (legacy)
            assigned_only: Only return assigned issues (legacy)
            hygiene_issues_only: Only return issues with hygiene problems (legacy)

        Returns:
            List of Issue objects
        """
        # Build IssueFilter from legacy parameters if not provided
        if issue_filter is None:
            issue_filter = IssueFilter(
                repo=repo,
                assignee=assignee,
                priority=priority,
                stale_only=stale_only,
                unassigned_only=unassigned_only,
                assigned_only=assigned_only,
                hygiene_issues_only=hygiene_issues_only
            )

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # Use IssueFilter's SQL generation
            where_clause, params = issue_filter.to_sql_conditions()
            query = f"SELECT * FROM issue_cache WHERE {where_clause} ORDER BY updated_at DESC"

            if issue_filter.limit:
                query += f" LIMIT {issue_filter.limit}"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            # Convert rows to Issue objects
            issues = []
            for row in rows:
                labels = []
                if row["labels"]:
                    try:
                        labels = json.loads(row["labels"])
                    except json.JSONDecodeError:
                        labels = []

                issue = Issue(
                    number=row["issue_number"],
                    title=row["title"],
                    repo=row["repo"],
                    assignee=row["assignee"],
                    priority=row["priority"],
                    labels=labels,
                    status=None,
                    issue_type=None,
                    created=row["created_at"] or "",
                    updated=row["updated_at"] or "",
                    url=row["url"],
                    is_stale=bool(row["is_stale"])
                )
                issues.append(issue)

            return issues

        except Exception as e:
            self.logger.error(f"Failed to load from DB: {e}")
            return []

    def _save_to_db(self, issues: list[Issue]) -> None:
        """
        Save issues to SQLite database.

        Clears existing cache and inserts new issues.
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # Clear existing cache
            cursor.execute("DELETE FROM issue_cache")

            # Insert new issues
            for issue in issues:
                labels_json = json.dumps(issue.labels) if issue.labels else "[]"
                cursor.execute("""
                    INSERT INTO issue_cache
                    (repo, issue_number, title, assignee, priority, labels,
                     created_at, updated_at, days_since_update, url, is_stale)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    issue.repo,
                    issue.number,
                    issue.title,
                    issue.assignee,
                    issue.priority,
                    labels_json,
                    issue.created,  # Issue uses 'created' not 'created_at'
                    issue.updated,  # Issue uses 'updated' not 'updated_at'
                    0,  # days_since_update calculated from is_stale
                    issue.url,
                    1 if issue.is_stale else 0
                ))

            conn.commit()
            conn.close()

            self.logger.info(f"Saved {len(issues)} issues to database")

        except Exception as e:
            self.logger.error(f"Failed to save to DB: {e}")

    def refresh(self) -> dict:
        """
        Manually refresh the cache from GitHub.

        Returns status information about the refresh.

        Returns:
            Dict with refresh status (success, count, duration)
        """
        with self._lock:
            if self._is_fetching:
                return {
                    "success": False,
                    "message": "Refresh already in progress",
                    "count": self.issue_count
                }
            self._is_fetching = True

        try:
            start = time.time()
            self.logger.info(f"Manual refresh from {len(self.repos)} repos...")

            issues = self.github_client.fetch_issues(self.repos)

            self._save_to_db(issues)
            self._save_metadata()

            elapsed = time.time() - start
            self.logger.info(f"Refresh complete: {len(issues)} issues in {elapsed:.1f}s")

            return {
                "success": True,
                "count": len(issues),
                "duration_seconds": round(elapsed, 1),
                "repos": len(self.repos)
            }

        except Exception as e:
            self.logger.error(f"Refresh failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "count": self.issue_count
            }

        finally:
            with self._lock:
                self._is_fetching = False

    def _refresh_sync(self) -> None:
        """Synchronous refresh - used for initial load only."""
        with self._lock:
            if self._is_fetching:
                return
            self._is_fetching = True

        try:
            start = time.time()
            self.logger.info(f"Sync refresh from {len(self.repos)} repos...")

            issues = self.github_client.fetch_issues(self.repos)

            self._save_to_db(issues)
            self._save_metadata()

            elapsed = time.time() - start
            self.logger.info(f"Sync refresh complete: {len(issues)} issues in {elapsed:.1f}s")

        except Exception as e:
            self.logger.error(f"Sync refresh failed: {e}")

        finally:
            with self._lock:
                self._is_fetching = False

    def _start_background_refresh(self) -> None:
        """Start a background refresh thread."""
        with self._lock:
            if self._is_fetching:
                self.logger.debug("Refresh already in progress, skipping")
                return
            self._is_fetching = True

        thread = Thread(target=self._refresh_async, daemon=True)
        thread.start()

    def _refresh_async(self) -> None:
        """Background refresh - runs in a separate thread."""
        try:
            start = time.time()
            self.logger.info(f"Background refresh from {len(self.repos)} repos...")

            issues = self.github_client.fetch_issues(self.repos)

            self._save_to_db(issues)
            self._save_metadata()

            elapsed = time.time() - start
            self.logger.info(f"Background refresh complete: {len(issues)} issues in {elapsed:.1f}s")

        except Exception as e:
            self.logger.error(f"Background refresh failed: {e}")

        finally:
            with self._lock:
                self._is_fetching = False

    def invalidate(self) -> None:
        """Clear the cache. Next get_issues() will trigger a refresh."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM issue_cache")
            cursor.execute("DELETE FROM cache_metadata WHERE key = 'last_refresh'")
            conn.commit()
            conn.close()
            self._last_refresh = None
            self.logger.info("Cache invalidated")
        except Exception as e:
            self.logger.error(f"Failed to invalidate cache: {e}")

    def get_filtered(
        self,
        issue_filter: Optional[IssueFilter] = None,
        # Legacy parameters for backwards compatibility
        repo: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: Optional[str] = None,
        stale_only: bool = False,
        unassigned_only: bool = False,
        assigned_only: bool = False,
        hygiene_issues_only: bool = False,
    ) -> list[Issue]:
        """
        Get filtered issues from cache.

        All filtering happens in SQLite for fast queries.

        Args:
            issue_filter: IssueFilter object with filter parameters (preferred)
            repo: Filter to specific repository (legacy)
            assignee: Filter to specific assignee (legacy)
            priority: Filter to specific priority level (legacy)
            stale_only: Only return stale issues (legacy)
            unassigned_only: Only return unassigned issues (legacy)
            assigned_only: Only return assigned issues (legacy)
            hygiene_issues_only: Only return issues with hygiene problems (legacy)

        Returns:
            Filtered list of Issue objects

        Examples:
            # New API using IssueFilter
            issues = cache.get_filtered(IssueFilter.high_priority())
            issues = cache.get_filtered(IssueFilter(repo="hermes", stale_only=True))

            # Legacy API (still supported)
            issues = cache.get_filtered(repo="hermes", priority="high")
        """
        # Ensure we have data
        if not self.has_data and not self._is_fetching:
            self.logger.info("Cache empty, performing initial load...")
            self._refresh_sync()

        # Use IssueFilter if provided, otherwise build from legacy params
        if issue_filter is not None:
            return self._load_from_db(issue_filter=issue_filter)

        return self._load_from_db(
            repo=repo,
            assignee=assignee,
            priority=priority,
            stale_only=stale_only,
            unassigned_only=unassigned_only,
            assigned_only=assigned_only,
            hygiene_issues_only=hygiene_issues_only
        )

    def get_stats(self) -> dict:
        """
        Get summary statistics for cached issues.

        Uses SQL aggregation for efficient stats.

        Returns:
            Dictionary with issue counts by category
        """
        # Ensure we have data
        if not self.has_data and not self._is_fetching:
            self.logger.info("Cache empty, performing initial load...")
            self._refresh_sync()

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # Get counts in a single query
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN assignee IS NOT NULL AND assignee != '' THEN 1 ELSE 0 END) as assigned,
                    SUM(CASE WHEN assignee IS NULL OR assignee = '' THEN 1 ELSE 0 END) as unassigned,
                    SUM(CASE WHEN is_stale = 1 THEN 1 ELSE 0 END) as stale,
                    SUM(CASE WHEN LOWER(priority) = 'high' THEN 1 ELSE 0 END) as high_priority,
                    SUM(CASE WHEN priority IS NULL OR priority = '' THEN 1 ELSE 0 END) as missing_priority
                FROM issue_cache
            """)
            row = cursor.fetchone()

            # Get by-repo counts
            cursor.execute("""
                SELECT repo, COUNT(*) as count
                FROM issue_cache
                GROUP BY repo
                ORDER BY count DESC
            """)
            by_repo = {r["repo"]: r["count"] for r in cursor.fetchall()}

            conn.close()

            return {
                "total": row["total"] or 0,
                "assigned": row["assigned"] or 0,
                "unassigned": row["unassigned"] or 0,
                "stale": row["stale"] or 0,
                "high_priority": row["high_priority"] or 0,
                "missing_priority": row["missing_priority"] or 0,
                "by_repo": by_repo,
                "cache_age_seconds": self.age_seconds,
                "is_refreshing": self._is_fetching,
            }

        except Exception as e:
            self.logger.error(f"Failed to get stats: {e}")
            return {
                "total": 0,
                "assigned": 0,
                "unassigned": 0,
                "stale": 0,
                "high_priority": 0,
                "missing_priority": 0,
                "by_repo": {},
                "cache_age_seconds": self.age_seconds,
                "error": str(e)
            }

    def get_repo_issues(self, repo: str) -> list[Issue]:
        """
        Get issues for a single repo from cache.

        Returns instantly from SQLite - no GitHub fetch.

        Args:
            repo: Repository name to get issues for

        Returns:
            List of Issue objects for that repo
        """
        # Ensure we have data
        if not self.has_data and not self._is_fetching:
            self.logger.info("Cache empty, performing initial load...")
            self._refresh_sync()

        return self._load_from_db(repo=repo)

    # =========================================================================
    # Report Methods - Used by ReportService for generating reports
    # =========================================================================

    def get_detailed_repo_stats(self) -> list[dict]:
        """
        Get detailed statistics per repository.

        Returns list of dicts with: name, full_name, open, high, unassigned, stale
        """
        # Ensure we have data
        if not self.has_data and not self._is_fetching:
            self.logger.info("Cache empty, performing initial load...")
            self._refresh_sync()

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    repo,
                    COUNT(*) as open_count,
                    SUM(CASE WHEN LOWER(priority) = 'high' THEN 1 ELSE 0 END) as high_count,
                    SUM(CASE WHEN assignee IS NULL OR assignee = '' THEN 1 ELSE 0 END) as unassigned_count,
                    SUM(CASE WHEN is_stale = 1 THEN 1 ELSE 0 END) as stale_count
                FROM issue_cache
                GROUP BY repo
                ORDER BY open_count DESC
            """)

            results = []
            for row in cursor.fetchall():
                repo_full = row["repo"]
                repo_name = repo_full.split("/")[-1] if "/" in repo_full else repo_full

                results.append({
                    "name": repo_name,
                    "full_name": repo_full,
                    "open": row["open_count"],
                    "high": row["high_count"],
                    "unassigned": row["unassigned_count"],
                    "stale": row["stale_count"],
                })

            conn.close()
            return results

        except Exception as e:
            self.logger.error(f"Failed to get detailed repo stats: {e}")
            return []

    def get_assignee_stats(self) -> list[tuple[str, int]]:
        """
        Get issue counts by assignee.

        Returns list of (assignee, count) tuples ordered by count descending.
        """
        # Ensure we have data
        if not self.has_data and not self._is_fetching:
            self.logger.info("Cache empty, performing initial load...")
            self._refresh_sync()

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT assignee, COUNT(*) as count
                FROM issue_cache
                WHERE assignee IS NOT NULL AND assignee != ''
                GROUP BY assignee
                ORDER BY count DESC
            """)

            results = [(row[0], row[1]) for row in cursor.fetchall()]
            conn.close()
            return results

        except Exception as e:
            self.logger.error(f"Failed to get assignee stats: {e}")
            return []

    def get_detailed_repo_stats_with_types(self, determine_type_func) -> list[dict]:
        """
        Get detailed statistics per repository including type breakdown.

        Args:
            determine_type_func: Function that takes labels list and returns type string

        Returns list of dicts with: name, full_name, open, closed, tasks, bugs, features, not_specified
        """
        # Ensure we have data
        if not self.has_data and not self._is_fetching:
            self.logger.info("Cache empty, performing initial load...")
            self._refresh_sync()

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("SELECT repo, labels FROM issue_cache")
            rows = cursor.fetchall()

            # Count by repo and type
            repo_data = {}
            for row in rows:
                repo = row["repo"]
                if repo not in repo_data:
                    repo_data[repo] = {
                        'open': 0, 'tasks': 0, 'bugs': 0,
                        'features': 0, 'not_specified': 0
                    }

                repo_data[repo]['open'] += 1

                # Parse labels to determine type
                labels = []
                if row["labels"]:
                    try:
                        labels = json.loads(row["labels"])
                    except (json.JSONDecodeError, TypeError):
                        labels = []

                issue_type = determine_type_func(labels)
                if issue_type == 'Task':
                    repo_data[repo]['tasks'] += 1
                elif issue_type == 'Bug':
                    repo_data[repo]['bugs'] += 1
                elif issue_type == 'Feature':
                    repo_data[repo]['features'] += 1
                else:
                    repo_data[repo]['not_specified'] += 1

            conn.close()

            # Convert to list format
            results = []
            for repo_full, data in sorted(repo_data.items(), key=lambda x: -x[1]['open']):
                repo_name = repo_full.split("/")[-1] if "/" in repo_full else repo_full
                results.append({
                    "name": repo_name,
                    "full_name": repo_full,
                    "open": data['open'],
                    "closed": 0,  # We only track open issues
                    "tasks": data['tasks'],
                    "bugs": data['bugs'],
                    "features": data['features'],
                    "not_specified": data['not_specified'],
                })

            return results

        except Exception as e:
            self.logger.error(f"Failed to get detailed repo stats with types: {e}")
            return []

    def get_assignee_by_repo_stats(self) -> dict[tuple[str, str], int]:
        """
        Get issue counts by (assignee, repo) pair for matrix reports.

        Returns dict mapping (assignee, repo) tuples to counts.
        """
        # Ensure we have data
        if not self.has_data and not self._is_fetching:
            self.logger.info("Cache empty, performing initial load...")
            self._refresh_sync()

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT assignee, repo, COUNT(*) as count
                FROM issue_cache
                WHERE assignee IS NOT NULL AND assignee != ''
                GROUP BY assignee, repo
            """)

            results = {}
            for row in cursor.fetchall():
                results[(row[0], row[1])] = row[2]

            conn.close()
            return results

        except Exception as e:
            self.logger.error(f"Failed to get assignee by repo stats: {e}")
            return {}

    def get_all_issues_dict(self) -> list[dict]:
        """
        Get all issues from cache as dictionaries.

        Returns list of dicts with: repo, issue_number, title, assignee, priority,
        labels, created_at, updated_at, url, is_stale
        """
        # Ensure we have data
        if not self.has_data and not self._is_fetching:
            self.logger.info("Cache empty, performing initial load...")
            self._refresh_sync()

        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT repo, issue_number, title, assignee, priority,
                       labels, created_at, updated_at, url, is_stale
                FROM issue_cache
                ORDER BY repo, issue_number
            """)

            results = []
            for row in cursor.fetchall():
                labels = []
                if row["labels"]:
                    try:
                        labels = json.loads(row["labels"])
                    except (json.JSONDecodeError, TypeError):
                        labels = []

                results.append({
                    "repo": row["repo"],
                    "issue_number": row["issue_number"],
                    "title": row["title"],
                    "assignee": row["assignee"],
                    "priority": row["priority"],
                    "labels": labels,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "url": row["url"],
                    "is_stale": bool(row["is_stale"]),
                })

            conn.close()
            return results

        except Exception as e:
            self.logger.error(f"Failed to get all issues: {e}")
            return []
