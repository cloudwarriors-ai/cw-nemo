"""
Database operations for QA Bot.

Handles SQLite database queries for intern tracking, escalations,
and conversation context.

Note: Schema definitions have been extracted to src/bot/db/schema.py
Note: AsyncDatabaseWriter has been extracted to src/bot/db/async_writer.py
"""
import json
import logging
import re
import sqlite3
import time
from datetime import datetime
from typing import Optional, Any

# Import from db package for backward compatibility
from .db.async_writer import (
    AsyncDatabaseWriter,
    WriteOperation,
    get_async_writer,
    reset_async_writer,
    _async_writer,
    _async_writer_lock,
)
from .db.schema import init_db


logger = logging.getLogger("qa_agent")


def log_query_async(
    db_path: str,
    user_id: str,
    query_type: str,
    query_text: str,
    response_time_ms: int,
    success: bool = True
) -> None:
    """
    Log a query asynchronously (non-blocking).

    DEPRECATED: Use log_query() instead, which defaults to async mode.
    This function is kept for backwards compatibility but simply delegates
    to log_query(use_async=True).

    Args:
        db_path: Path to database
        user_id: User who made the query
        query_type: Type of query (high_priority, summary, etc.)
        query_text: Original query text
        response_time_ms: Response time in milliseconds
        success: Whether query was successful
    """
    # Delegate to unified log_query function
    log_query(
        db_path=db_path,
        user_id=user_id,
        query_type=query_type,
        query_text=query_text,
        response_time_ms=response_time_ms,
        success=success,
        use_async=True
    )


def validate_date(date_str: Optional[str]) -> Optional[str]:
    """
    Validate date string is in YYYY-MM-DD format.

    Args:
        date_str: Date string to validate

    Returns:
        The validated date string, or None if input is None

    Raises:
        ValueError: If date format is invalid
    """
    if date_str is None:
        return None

    # Check format with regex
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        raise ValueError(f"Invalid date format: {date_str}. Expected YYYY-MM-DD")

    # Validate it's a real date
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date: {date_str}")

    return date_str


def get_intern_status(db_path: str, name: Optional[str] = None) -> Optional[dict]:
    """
    Get intern status and task summary.

    Args:
        db_path: Path to database
        name: Intern name to look up (partial match). If None, returns summary of all.

    Returns:
        Dictionary with intern info and tasks, or None if not found
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if name:
        # Find specific intern (partial name match)
        cursor.execute("""
            SELECT * FROM interns
            WHERE LOWER(name) LIKE LOWER(?)
            LIMIT 1
        """, (f"%{name}%",))

        intern_row = cursor.fetchone()

        if not intern_row:
            conn.close()
            return None

        intern = dict(intern_row)

        # Get task summary
        cursor.execute("""
            SELECT
                SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) as blocked,
                SUM(CASE WHEN status = 'assigned' THEN 1 ELSE 0 END) as assigned
            FROM tasks
            WHERE intern_id = ?
        """, (intern["id"],))

        task_row = cursor.fetchone()
        intern["tasks"] = dict(task_row) if task_row else {}

        # Get recent activity (completed tasks)
        cursor.execute("""
            SELECT title, completed_at
            FROM tasks
            WHERE intern_id = ? AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 5
        """, (intern["id"],))

        intern["recent_activity"] = [
            f"Completed: {row['title']}" for row in cursor.fetchall()
        ]

        conn.close()
        return intern

    else:
        # Return summary of all active interns
        cursor.execute("""
            SELECT id, name, program, status, supervisor
            FROM interns
            WHERE status != 'completed'
            ORDER BY name
        """)

        interns = [dict(row) for row in cursor.fetchall()]
        conn.close()

        if not interns:
            return None

        return {
            "name": "All Interns",
            "interns": interns,
            "total": len(interns)
        }


def add_intern(
    db_path: str,
    intern_id: str,
    name: str,
    program: str = None,
    supervisor: str = None,
    start_date: str = None,
    end_date: str = None,
    email: str = None
) -> bool:
    """
    Add a new intern to the database.

    DEPRECATED: Use InternRepository.create() instead.
    This function is kept for backward compatibility with tests.

    Args:
        db_path: Path to database
        intern_id: Unique identifier
        name: Intern's full name
        program: Program name (skillbridge, vanderbilt, etc.)
        supervisor: Supervisor name
        start_date: Start date (YYYY-MM-DD)
        end_date: Expected end date (YYYY-MM-DD)
        email: Intern's email address

    Returns:
        True if successful

    Raises:
        ValueError: If date format is invalid
    """
    # Validate dates before inserting
    start_date = validate_date(start_date)
    end_date = validate_date(end_date)

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO interns (id, name, program, supervisor, start_date, end_date, email)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (intern_id, name, program, supervisor, start_date, end_date, email))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        logger.error(f"Failed to add intern: {e}")
        return False


def assign_task(
    db_path: str,
    task_id: str,
    intern_id: str,
    title: str,
    github_issue: str = None,
    description: str = None
) -> bool:
    """
    Assign a task to an intern.

    Args:
        db_path: Path to database
        task_id: Unique task identifier
        intern_id: Intern's ID
        title: Task title
        github_issue: GitHub issue reference (e.g., "repo#123")
        description: Task description

    Returns:
        True if successful
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO tasks (id, intern_id, title, github_issue, description)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, intern_id, title, github_issue, description))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        logger.error(f"Failed to assign task: {e}")
        return False


def update_task_status(
    db_path: str,
    task_id: str,
    status: str,
    notes: str = None
) -> bool:
    """
    Update task status.

    Args:
        db_path: Path to database
        task_id: Task identifier
        status: New status (assigned, in_progress, completed, blocked)
        notes: Optional notes

    Returns:
        True if successful
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        completed_at = datetime.now().isoformat() if status == "completed" else None

        cursor.execute("""
            UPDATE tasks
            SET status = ?, completed_at = ?, notes = COALESCE(?, notes)
            WHERE id = ?
        """, (status, completed_at, notes, task_id))

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    except Exception as e:
        logger.error(f"Failed to update task: {e}")
        return False


def log_query(
    db_path: str,
    user_id: str,
    query_type: str,
    query_text: str,
    response_time_ms: int,
    success: bool = True,
    use_async: bool = True
) -> None:
    """
    Log a query for analytics.

    By default uses async (non-blocking) mode for better performance.
    Set use_async=False for synchronous mode if needed (e.g., during shutdown).

    Args:
        db_path: Path to database
        user_id: User who made the query
        query_type: Type of query (high_priority, summary, etc.)
        query_text: Original query text
        response_time_ms: Response time in milliseconds
        success: Whether query was successful
        use_async: If True (default), use non-blocking async writer.
                   If False, use synchronous database write.
    """
    if use_async:
        # Preferred: non-blocking async write
        try:
            writer = get_async_writer(db_path)
            writer.execute(
                "INSERT INTO query_log (user_id, query_type, query_text, response_time_ms, success) VALUES (?, ?, ?, ?, ?)",
                (user_id, query_type, query_text[:500], response_time_ms, success)
            )
        except Exception as e:
            logger.warning(f"Async log_query failed, falling back to sync: {e}")
            # Fall back to sync on async failure
            _log_query_sync(db_path, user_id, query_type, query_text, response_time_ms, success)
    else:
        # Synchronous write (blocking)
        _log_query_sync(db_path, user_id, query_type, query_text, response_time_ms, success)


def _log_query_sync(
    db_path: str,
    user_id: str,
    query_type: str,
    query_text: str,
    response_time_ms: int,
    success: bool
) -> None:
    """
    Internal synchronous query logging.

    Used by log_query() when use_async=False or as fallback.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO query_log (user_id, query_type, query_text, response_time_ms, success)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, query_type, query_text[:500], response_time_ms, success))

        conn.commit()
        conn.close()

    except Exception as e:
        logger.warning(f"Failed to log query (sync): {e}")


def get_intern_by_id(db_path: str, intern_id: str) -> Optional[dict]:
    """
    Get intern by ID.

    Args:
        db_path: Path to database
        intern_id: Intern's unique ID

    Returns:
        Intern details or None if not found
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM interns WHERE id = ?", (intern_id,))
        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    except Exception as e:
        logger.warning(f"Failed to get intern: {e}")
        return None


def get_all_interns(
    db_path: str,
    status: Optional[str] = None,
    include_tasks: bool = False
) -> list[dict]:
    """
    Get all interns, optionally filtered by status.

    Args:
        db_path: Path to database
        status: Filter by status (onboarding, active, graduating, completed)
        include_tasks: Include task counts for each intern

    Returns:
        List of intern records
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if status:
            cursor.execute(
                "SELECT * FROM interns WHERE status = ? ORDER BY name",
                (status,)
            )
        else:
            cursor.execute("SELECT * FROM interns ORDER BY name")

        interns = [dict(row) for row in cursor.fetchall()]

        if include_tasks:
            for intern in interns:
                cursor.execute("""
                    SELECT
                        SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) as blocked,
                        SUM(CASE WHEN status = 'assigned' THEN 1 ELSE 0 END) as assigned
                    FROM tasks WHERE intern_id = ?
                """, (intern["id"],))
                task_row = cursor.fetchone()
                intern["tasks"] = dict(task_row) if task_row else {}

        conn.close()
        return interns

    except Exception as e:
        logger.warning(f"Failed to get interns: {e}")
        return []


def update_intern_status(
    db_path: str,
    intern_id: str,
    status: str,
    notes: str = None
) -> bool:
    """
    Update an intern's status.

    Args:
        db_path: Path to database
        intern_id: Intern's unique ID
        status: New status (onboarding, active, graduating, completed)
        notes: Optional notes

    Returns:
        True if successful
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE interns
            SET status = ?, notes = COALESCE(?, notes), updated_at = ?
            WHERE id = ?
        """, (status, notes, datetime.now().isoformat(), intern_id))

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    except Exception as e:
        logger.error(f"Failed to update intern status: {e}")
        return False


def get_intern_tasks(
    db_path: str,
    intern_id: str,
    status: Optional[str] = None,
    since: Optional[str] = None
) -> list[dict]:
    """
    Get tasks for an intern.

    Args:
        db_path: Path to database
        intern_id: Intern's unique ID
        status: Filter by task status
        since: Filter tasks completed since this date (YYYY-MM-DD)

    Returns:
        List of task records
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM tasks WHERE intern_id = ?"
        params = [intern_id]

        if status:
            query += " AND status = ?"
            params.append(status)

        if since:
            query += " AND (completed_at >= ? OR completed_at IS NULL)"
            params.append(since)

        query += " ORDER BY assigned_at DESC"

        cursor.execute(query, params)
        tasks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tasks

    except Exception as e:
        logger.warning(f"Failed to get intern tasks: {e}")
        return []


def get_interns_ending_soon(db_path: str, days: int = 7) -> list[dict]:
    """
    Get interns whose internship ends within the specified days.

    Useful for triggering offboarding workflows.

    Args:
        db_path: Path to database
        days: Number of days to look ahead

    Returns:
        List of intern records
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM interns
            WHERE end_date IS NOT NULL
            AND end_date <= date('now', ?)
            AND end_date >= date('now')
            AND status NOT IN ('completed', 'graduating')
            ORDER BY end_date
        """, (f"+{days} days",))

        interns = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return interns

    except Exception as e:
        logger.warning(f"Failed to get interns ending soon: {e}")
        return []


def get_workflow_execution(db_path: str, execution_id: str) -> Optional[dict]:
    """
    Get a workflow execution by ID.

    Args:
        db_path: Path to database
        execution_id: Execution ID

    Returns:
        Execution record or None if not found
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, workflow_type, status, triggered_at, completed_at, result
            FROM workflow_executions
            WHERE id = ?
        """, (execution_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    except Exception as e:
        logger.warning(f"Failed to get workflow execution: {e}")
        return None


def get_recent_executions(
    db_path: str,
    limit: int = 10,
    workflow_type: str = None
) -> list[dict]:
    """
    Get recent workflow executions.

    Args:
        db_path: Path to database
        limit: Maximum number of executions to return
        workflow_type: Optional filter by workflow type

    Returns:
        List of execution records
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if workflow_type:
            cursor.execute("""
                SELECT id, workflow_type, status, triggered_at, completed_at, result
                FROM workflow_executions
                WHERE workflow_type = ?
                ORDER BY triggered_at DESC
                LIMIT ?
            """, (workflow_type, limit))
        else:
            cursor.execute("""
                SELECT id, workflow_type, status, triggered_at, completed_at, result
                FROM workflow_executions
                ORDER BY triggered_at DESC
                LIMIT ?
            """, (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    except Exception as e:
        logger.warning(f"Failed to get recent executions: {e}")
        return []


def update_workflow_execution(
    db_path: str,
    execution_id: str,
    status: str,
    result: dict = None
) -> bool:
    """
    Update a workflow execution status.

    Args:
        db_path: Path to database
        execution_id: Execution ID to update
        status: New status
        result: Optional result data

    Returns:
        True if update succeeded
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        result_json = json.dumps(result) if result else None
        completed_at = datetime.now().isoformat() if status in ['completed', 'failed'] else None

        cursor.execute("""
            UPDATE workflow_executions
            SET status = ?, completed_at = ?, result = ?
            WHERE id = ?
        """, (status, completed_at, result_json, execution_id))

        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return updated

    except Exception as e:
        logger.warning(f"Failed to update workflow execution: {e}")
        return False


def get_meeting_transcript(db_path: str, meeting_id: str) -> Optional[dict]:
    """
    Get transcript and metadata for a meeting.

    Args:
        db_path: Path to database
        meeting_id: Meeting ID

    Returns:
        Dictionary with transcript, participants, date, duration, etc.
        Or None if not found.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get meeting info
        cursor.execute("""
            SELECT id, meeting_url, status, created_at, ended_at
            FROM meetings
            WHERE id = ?
        """, (meeting_id,))

        meeting = cursor.fetchone()
        if not meeting:
            conn.close()
            return None

        # Get transcript segments
        cursor.execute("""
            SELECT speaker, text, start_time, end_time
            FROM transcript_segments
            WHERE meeting_id = ?
            ORDER BY start_time
        """, (meeting_id,))

        segments = cursor.fetchall()
        conn.close()

        if not segments:
            return {
                "meeting_id": meeting_id,
                "transcript": None,
                "participants": [],
                "meeting_date": meeting["created_at"],
                "duration": None,
            }

        # Build transcript text
        transcript_lines = []
        participants = set()
        for seg in segments:
            speaker = seg["speaker"] or "Unknown"
            participants.add(speaker)
            transcript_lines.append(f"{speaker}: {seg['text']}")

        # Calculate duration if ended
        duration = None
        if meeting["ended_at"] and meeting["created_at"]:
            try:
                start = datetime.fromisoformat(meeting["created_at"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(meeting["ended_at"].replace("Z", "+00:00"))
                diff = end - start
                minutes = int(diff.total_seconds() / 60)
                duration = f"{minutes} minutes"
            except (ValueError, AttributeError):
                pass

        return {
            "meeting_id": meeting_id,
            "transcript": "\n".join(transcript_lines),
            "participants": list(participants),
            "meeting_date": meeting["created_at"],
            "duration": duration,
        }

    except Exception as e:
        logger.warning(f"Failed to get meeting transcript: {e}")
        return None


def get_query_stats(db_path: str, days: int = 7) -> dict:
    """
    Get query statistics for the past N days.

    Args:
        db_path: Path to database
        days: Number of days to look back

    Returns:
        Dictionary with query statistics
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                query_type,
                COUNT(*) as count,
                AVG(response_time_ms) as avg_response_time,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate
            FROM query_log
            WHERE created_at > datetime('now', ?)
            GROUP BY query_type
            ORDER BY count DESC
        """, (f"-{days} days",))

        stats = {row[0]: {
            "count": row[1],
            "avg_response_time_ms": row[2],
            "success_rate": row[3]
        } for row in cursor.fetchall()}

        conn.close()
        return stats

    except Exception as e:
        logger.warning(f"Failed to get query stats: {e}")
        return {}


# =============================================================================
# Database Migrations
# =============================================================================

def migrate_add_github_username(db_path: str) -> bool:
    """
    Safe migration to add github_username column to interns table.

    Checks if column exists first to avoid duplicate column errors.

    Args:
        db_path: Path to database

    Returns:
        True if migration succeeded or column already exists
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if column exists
        cursor.execute("PRAGMA table_info(interns)")
        columns = [row[1] for row in cursor.fetchall()]

        if "github_username" not in columns:
            cursor.execute("ALTER TABLE interns ADD COLUMN github_username TEXT")
            conn.commit()
            logger.info("Migration: Added github_username column to interns table")
        else:
            logger.debug("Migration: github_username column already exists")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False


def run_migrations(db_path: str) -> None:
    """
    Run all database migrations.

    Call this on app startup after init_db().

    Args:
        db_path: Path to database
    """
    migrate_add_github_username(db_path)
    logger.info("Database migrations completed")


# =============================================================================
# Intern Lookup Functions (for onboarding/offboarding)
# =============================================================================

def get_intern_by_name(db_path: str, name: str) -> list[dict]:
    """
    Find interns by partial name match.

    DEPRECATED: Use InternRepository.get_by_name() instead.
    This function is kept for backward compatibility with tests.

    Args:
        db_path: Path to database
        name: Name to search for (partial match, case-insensitive)

    Returns:
        List of matching intern records
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM interns
            WHERE LOWER(name) LIKE LOWER(?)
            ORDER BY name
        """, (f"%{name}%",))

        interns = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return interns

    except Exception as e:
        logger.warning(f"Failed to get intern by name: {e}")
        return []


def get_intern_by_email(db_path: str, email: str) -> Optional[dict]:
    """
    Find intern by exact email match.

    Args:
        db_path: Path to database
        email: Email address (exact match, case-insensitive)

    Returns:
        Intern record or None if not found
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM interns
            WHERE LOWER(email) = LOWER(?)
        """, (email,))

        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    except Exception as e:
        logger.warning(f"Failed to get intern by email: {e}")
        return None


def check_duplicate_intern(db_path: str, name: str, email: str) -> list[dict]:
    """
    Check for existing interns with matching name or email.

    DEPRECATED: Use InternRepository.check_duplicate() instead.
    This function is kept for backward compatibility with tests.

    Args:
        db_path: Path to database
        name: Intern name to check
        email: Email address to check

    Returns:
        List of potential duplicate intern records
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM interns
            WHERE LOWER(name) = LOWER(?)
               OR LOWER(email) = LOWER(?)
            ORDER BY created_at DESC
        """, (name, email))

        duplicates = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return duplicates

    except Exception as e:
        logger.warning(f"Failed to check for duplicate intern: {e}")
        return []


def update_intern_github_username(
    db_path: str,
    intern_id: str,
    github_username: str
) -> bool:
    """
    Update an intern's GitHub username.

    Args:
        db_path: Path to database
        intern_id: Intern's unique ID
        github_username: GitHub username

    Returns:
        True if successful
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE interns
            SET github_username = ?, updated_at = ?
            WHERE id = ?
        """, (github_username, datetime.now().isoformat(), intern_id))

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    except Exception as e:
        logger.error(f"Failed to update intern github username: {e}")
        return False


# =============================================================================
# Conversation Flow Functions (multi-worker safe)
# =============================================================================

def create_conversation_flow(
    db_path: str,
    flow_id: str,
    user_id: str,
    flow_type: str,
    channel_id: str = None,
    expires_minutes: int = 10
) -> bool:
    """
    Create a new conversation flow.

    DEPRECATED: Use ConversationFlowRepository.create() instead.
    This function is kept for backward compatibility with tests.

    Args:
        db_path: Path to database
        flow_id: Unique flow identifier
        user_id: User who started the flow
        flow_type: Type of flow (onboarding, offboarding)
        channel_id: Channel where flow was started
        expires_minutes: Minutes until flow expires

    Returns:
        True if created successfully
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        expires_at = datetime.now().isoformat()
        # Calculate expiry (SQLite datetime format)
        cursor.execute("""
            INSERT INTO conversation_flows (id, user_id, channel_id, flow_type, collected_data, expires_at)
            VALUES (?, ?, ?, ?, '{}', datetime('now', ?))
        """, (flow_id, user_id, channel_id, flow_type, f"+{expires_minutes} minutes"))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        logger.error(f"Failed to create conversation flow: {e}")
        return False


def get_active_flow(db_path: str, user_id: str) -> Optional[dict]:
    """
    Get active conversation flow for a user.

    DEPRECATED: Use ConversationFlowRepository.get_active() instead.
    This function is kept for backward compatibility with tests.

    Args:
        db_path: Path to database
        user_id: User ID

    Returns:
        Flow record or None if no active flow
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get non-expired flow
        cursor.execute("""
            SELECT * FROM conversation_flows
            WHERE user_id = ?
            AND expires_at > datetime('now')
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            flow = dict(row)
            # Parse collected_data JSON
            flow["collected_data"] = json.loads(flow["collected_data"] or "{}")
            return flow
        return None

    except Exception as e:
        logger.warning(f"Failed to get active flow: {e}")
        return None


def update_conversation_flow(
    db_path: str,
    flow_id: str,
    current_step: int = None,
    collected_data: dict = None
) -> bool:
    """
    Update a conversation flow's progress.

    DEPRECATED: Use ConversationFlowRepository.update() instead.
    This function is kept for backward compatibility with tests.

    Args:
        db_path: Path to database
        flow_id: Flow identifier
        current_step: New step number
        collected_data: Updated collected data dict

    Returns:
        True if successful

    Security:
        Uses explicit UPDATE statements to avoid dynamic SQL construction.
        All values use parameterized queries for SQL injection protection.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Use explicit UPDATE statements - no dynamic SQL construction
        # SECURITY: Explicit statements eliminate any possibility of SQL injection
        # from future changes accidentally introducing user-controlled column names
        if current_step is not None and collected_data is not None:
            # Update both fields
            cursor.execute(
                "UPDATE conversation_flows SET current_step = ?, collected_data = ? WHERE id = ?",
                (current_step, json.dumps(collected_data), flow_id)
            )
        elif current_step is not None:
            # Update only current_step
            cursor.execute(
                "UPDATE conversation_flows SET current_step = ? WHERE id = ?",
                (current_step, flow_id)
            )
        elif collected_data is not None:
            # Update only collected_data
            cursor.execute(
                "UPDATE conversation_flows SET collected_data = ? WHERE id = ?",
                (json.dumps(collected_data), flow_id)
            )
        else:
            # Nothing to update
            conn.close()
            return True

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    except Exception as e:
        logger.error(f"Failed to update conversation flow: {e}")
        return False


def delete_conversation_flow(db_path: str, flow_id: str) -> bool:
    """
    Delete a conversation flow (on completion or cancellation).

    DEPRECATED: Use ConversationFlowRepository.delete() instead.
    This function is kept for backward compatibility with tests.

    Args:
        db_path: Path to database
        flow_id: Flow identifier

    Returns:
        True if deleted successfully
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM conversation_flows WHERE id = ?", (flow_id,))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        logger.error(f"Failed to delete conversation flow: {e}")
        return False


def cleanup_expired_flows(db_path: str) -> int:
    """
    Delete expired conversation flows.

    Should be called periodically to clean up stale flows.

    Args:
        db_path: Path to database

    Returns:
        Number of flows deleted
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM conversation_flows
            WHERE expires_at < datetime('now')
        """)

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted > 0:
            logger.debug(f"Cleaned up {deleted} expired conversation flows")
        return deleted

    except Exception as e:
        logger.warning(f"Failed to cleanup expired flows: {e}")
        return 0


# =============================================================================
# Audit Log Functions
# =============================================================================

def log_audit_event(
    db_path: str,
    action: str,
    actor_user_id: str,
    target_id: str = None,
    target_name: str = None,
    actor_name: str = None,
    details: str = None
) -> bool:
    """
    Log an audit event for compliance tracking.

    DEPRECATED: Use AuditRepository.log_event() instead.
    This function is kept for backward compatibility with tests.

    Args:
        db_path: Path to database
        action: Action type (onboard, offboard, etc.)
        actor_user_id: User who performed the action
        target_id: ID of the target (e.g., intern_id)
        target_name: Name of the target (e.g., intern name)
        actor_name: Name of the actor
        details: Additional details (JSON or text)

    Returns:
        True if logged successfully
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO audit_log (action, target_id, target_name, actor_user_id, actor_name, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (action, target_id, target_name, actor_user_id, actor_name, details))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        logger.error(f"Failed to log audit event: {e}")
        return False


def get_audit_log(
    db_path: str,
    action: str = None,
    actor_user_id: str = None,
    target_id: str = None,
    limit: int = 50
) -> list[dict]:
    """
    Get audit log entries with optional filters.

    DEPRECATED: Use AuditRepository.get_log() instead.
    This function is kept for backward compatibility with tests.

    Args:
        db_path: Path to database
        action: Filter by action type
        actor_user_id: Filter by actor
        target_id: Filter by target
        limit: Maximum entries to return

    Returns:
        List of audit log entries
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []

        if action:
            query += " AND action = ?"
            params.append(action)

        if actor_user_id:
            query += " AND actor_user_id = ?"
            params.append(actor_user_id)

        if target_id:
            query += " AND target_id = ?"
            params.append(target_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        entries = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return entries

    except Exception as e:
        logger.warning(f"Failed to get audit log: {e}")
        return []
