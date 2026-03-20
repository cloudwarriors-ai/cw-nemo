"""
Database schema definitions for QA Bot.

Contains all table creation and index definitions.
"""

import logging
import os
import sqlite3

logger = logging.getLogger("qa_agent")


# Schema version for migrations
SCHEMA_VERSION = 1


def init_db(db_path: str = "data/state.db") -> None:
    """
    Initialize the SQLite database with required tables.

    Creates tables if they don't exist. Safe to call multiple times.

    Args:
        db_path: Path to the SQLite database file
    """
    # Ensure directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create all tables
    _create_core_tables(cursor)
    _create_workflow_tables(cursor)
    _create_meeting_tables(cursor)
    _create_cache_tables(cursor)
    _create_indexes(cursor)

    conn.commit()
    conn.close()

    logger.info(f"Database initialized: {db_path}")


def _create_core_tables(cursor: sqlite3.Cursor) -> None:
    """Create core business tables."""
    # Interns table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            program TEXT,
            start_date DATE,
            end_date DATE,
            status TEXT DEFAULT 'onboarding',
            supervisor TEXT,
            email TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tasks assigned to interns
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            intern_id TEXT REFERENCES interns(id),
            title TEXT NOT NULL,
            github_issue TEXT,
            description TEXT,
            status TEXT DEFAULT 'assigned',
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            notes TEXT
        )
    """)

    # Escalations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS escalations (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            user_name TEXT,
            topic TEXT NOT NULL,
            channel_id TEXT,
            status TEXT DEFAULT 'pending',
            assigned_to TEXT,
            resolved_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            notes TEXT
        )
    """)

    # Conversation context (for multi-turn conversations)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            channel_id TEXT,
            context TEXT,
            last_query TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Query log for analytics
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            query_type TEXT,
            query_text TEXT,
            response_time_ms INTEGER,
            success BOOLEAN,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Rate limiting (for multi-worker support)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)

    # Audit log (track onboarding/offboarding actions for compliance)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            target_id TEXT,
            target_name TEXT,
            actor_user_id TEXT NOT NULL,
            actor_name TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _create_workflow_tables(cursor: sqlite3.Cursor) -> None:
    """Create workflow-related tables."""
    # Workflow executions (n8n integration)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id TEXT PRIMARY KEY,
            workflow_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            payload TEXT,
            context TEXT,
            result TEXT,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)

    # Conversation flows (for multi-turn onboarding/offboarding - multi-worker safe)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_flows (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            channel_id TEXT,
            flow_type TEXT NOT NULL,
            current_step INTEGER DEFAULT 0,
            collected_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        )
    """)


def _create_meeting_tables(cursor: sqlite3.Cursor) -> None:
    """Create meeting-related tables (Recall.ai integration)."""
    # Meetings (Recall.ai integration - Phase 3)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY,
            bot_id TEXT NOT NULL,
            meeting_url TEXT NOT NULL,
            requested_by TEXT,
            channel_id TEXT,
            status TEXT DEFAULT 'joining',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            ended_at TIMESTAMP
        )
    """)

    # Transcripts cache (full meeting transcripts)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            meeting_id TEXT PRIMARY KEY REFERENCES meetings(id),
            segments TEXT,
            fetched_at TIMESTAMP
        )
    """)

    # Real-time transcript segments
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transcript_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT REFERENCES meetings(id),
            speaker TEXT,
            text TEXT,
            start_time REAL,
            end_time REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _create_cache_tables(cursor: sqlite3.Cursor) -> None:
    """Create cache-related tables."""
    # GitHub issue cache (persistent storage for fast queries)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS issue_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT NOT NULL,
            issue_number INTEGER NOT NULL,
            title TEXT,
            assignee TEXT,
            priority TEXT,
            labels TEXT,
            created_at TEXT,
            updated_at TEXT,
            days_since_update INTEGER,
            url TEXT,
            is_stale BOOLEAN DEFAULT 0,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(repo, issue_number)
        )
    """)

    # Cache metadata (track when cache was last refreshed)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_metadata (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _create_indexes(cursor: sqlite3.Cursor) -> None:
    """Create indexes for common queries."""
    # Core table indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_interns_status
        ON interns(status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_intern
        ON tasks(intern_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_escalations_status
        ON escalations(status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_user
        ON conversations(user_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_rate_limits_user
        ON rate_limits(user_id, timestamp)
    """)

    # Workflow indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_workflow_status
        ON workflow_executions(status, workflow_type)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversation_flows_user
        ON conversation_flows(user_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversation_flows_expires
        ON conversation_flows(expires_at)
    """)

    # Meeting indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_meetings_status
        ON meetings(status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_meetings_bot
        ON meetings(bot_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_transcript_segments_meeting
        ON transcript_segments(meeting_id, start_time)
    """)

    # Cache indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_issue_cache_repo
        ON issue_cache(repo)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_issue_cache_assignee
        ON issue_cache(assignee)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_issue_cache_priority
        ON issue_cache(priority)
    """)

    # Audit indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_log_action
        ON audit_log(action, created_at)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_log_actor
        ON audit_log(actor_user_id)
    """)
