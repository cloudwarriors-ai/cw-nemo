"""
Query log repository.

Handles database operations for query logging and statistics.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional
import logging


class QueryLogRepository:
    """
    Repository for query logs and statistics.

    Provides operations for logging user queries and retrieving stats.
    """

    def __init__(
        self,
        db_path: str,
        logger: Optional[logging.Logger] = None
    ):
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)

    def log_query(
        self,
        user_id: str,
        query_type: str,
        query_text: str,
        response_time_ms: int,
        success: bool = True
    ) -> bool:
        """
        Log a user query.

        Args:
            user_id: User identifier
            query_type: Type of query (help, issues, summary, etc.)
            query_text: The query text
            response_time_ms: Response time in milliseconds
            success: Whether query was successful

        Returns:
            True if logged successfully
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO query_log (user_id, query_type, query_text, response_time_ms, success)
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                query_type,
                query_text[:500],  # Truncate long queries
                response_time_ms,
                success
            ))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            self.logger.warning(f"Failed to log query: {e}")
            return False

    def get_stats(self, days: int = 7) -> dict:
        """
        Get query statistics for the past N days.

        Args:
            days: Number of days to look back

        Returns:
            Stats dict with counts and breakdowns
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

            # Total queries
            cursor.execute(
                "SELECT COUNT(*) FROM query_log WHERE created_at >= ?",
                (cutoff,)
            )
            total = cursor.fetchone()[0]

            # Unique users
            cursor.execute(
                "SELECT COUNT(DISTINCT user_id) FROM query_log WHERE created_at >= ?",
                (cutoff,)
            )
            unique_users = cursor.fetchone()[0]

            # By query type
            cursor.execute("""
                SELECT query_type, COUNT(*) as count
                FROM query_log
                WHERE created_at >= ?
                GROUP BY query_type
                ORDER BY count DESC
            """, (cutoff,))
            by_type = {row[0]: row[1] for row in cursor.fetchall()}

            # Average latency
            cursor.execute("""
                SELECT AVG(response_time_ms)
                FROM query_log
                WHERE created_at >= ? AND response_time_ms IS NOT NULL
            """, (cutoff,))
            avg_latency = cursor.fetchone()[0]

            # Success rate
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                    COUNT(*) as total
                FROM query_log
                WHERE created_at >= ?
            """, (cutoff,))
            row = cursor.fetchone()
            success_rate = (row[0] / row[1] * 100) if row[1] > 0 else 100.0

            conn.close()

            return {
                "total_queries": total,
                "unique_users": unique_users,
                "by_type": by_type,
                "avg_latency_ms": round(avg_latency or 0, 2),
                "success_rate": round(success_rate, 1),
                "period_days": days
            }

        except Exception as e:
            self.logger.warning(f"Failed to get query stats: {e}")
            return {
                "total_queries": 0,
                "unique_users": 0,
                "by_type": {},
                "avg_latency_ms": 0,
                "success_rate": 100.0,
                "period_days": days
            }

    def get_recent(
        self,
        limit: int = 50,
        user_id: Optional[str] = None
    ) -> list[dict]:
        """
        Get recent queries.

        Args:
            limit: Maximum number of queries to return
            user_id: Optional filter by user

        Returns:
            List of query dicts
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if user_id:
                cursor.execute("""
                    SELECT * FROM query_log
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (user_id, limit))
            else:
                cursor.execute("""
                    SELECT * FROM query_log
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            self.logger.warning(f"Failed to get recent queries: {e}")
            return []

    def get_user_history(
        self,
        user_id: str,
        days: int = 30
    ) -> dict:
        """
        Get query history for a specific user.

        Args:
            user_id: User identifier
            days: Number of days to look back

        Returns:
            User history dict
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

            # Total queries by this user
            cursor.execute(
                "SELECT COUNT(*) FROM query_log WHERE user_id = ? AND created_at >= ?",
                (user_id, cutoff)
            )
            total = cursor.fetchone()[0]

            # Most common query types
            cursor.execute("""
                SELECT query_type, COUNT(*) as count
                FROM query_log
                WHERE user_id = ? AND created_at >= ?
                GROUP BY query_type
                ORDER BY count DESC
                LIMIT 5
            """, (user_id, cutoff))
            top_types = {row[0]: row[1] for row in cursor.fetchall()}

            conn.close()

            return {
                "user_id": user_id,
                "total_queries": total,
                "top_query_types": top_types,
                "period_days": days
            }

        except Exception as e:
            self.logger.warning(f"Failed to get user history: {e}")
            return {
                "user_id": user_id,
                "total_queries": 0,
                "top_query_types": {},
                "period_days": days
            }

    def cleanup_old(self, days: int = 90) -> int:
        """
        Delete old query logs.

        Args:
            days: Delete logs older than this many days

        Returns:
            Number of deleted records
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

            cursor.execute(
                "DELETE FROM query_log WHERE created_at < ?",
                (cutoff,)
            )

            deleted = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted > 0:
                self.logger.info(f"Cleaned up {deleted} old query logs")

            return deleted

        except Exception as e:
            self.logger.error(f"Failed to cleanup old queries: {e}")
            return 0
