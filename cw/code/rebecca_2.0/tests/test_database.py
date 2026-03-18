"""
Tests for database operations.
"""
import pytest
from src.bot.database import (
    init_db,
    get_intern_status,
    add_intern,
    assign_task,
    update_task_status,
    log_query,
    get_query_stats,
)


class TestDatabaseInit:
    """Test database initialization."""

    def test_init_creates_tables(self, temp_db):
        """Test that init_db creates all required tables."""
        import sqlite3
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Check tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        assert "interns" in tables
        assert "tasks" in tables
        assert "escalations" in tables
        assert "conversations" in tables
        assert "query_log" in tables

        conn.close()

    def test_init_is_idempotent(self, temp_db):
        """Test that init_db can be called multiple times safely."""
        init_db(temp_db)
        init_db(temp_db)  # Should not raise


class TestInternOperations:
    """Test intern database operations."""

    def test_add_intern(self, temp_db):
        """Test adding an intern."""
        result = add_intern(
            db_path=temp_db,
            intern_id="intern-1",
            name="Sara Johnson",
            program="skillbridge",
            supervisor="chad3"
        )
        assert result is True

    def test_get_intern_status_by_name(self, temp_db):
        """Test getting intern status by name."""
        add_intern(
            db_path=temp_db,
            intern_id="intern-2",
            name="Alex Smith",
            program="vanderbilt"
        )

        result = get_intern_status(temp_db, "alex")
        assert result is not None
        assert "Alex" in result["name"]

    def test_get_intern_status_not_found(self, temp_db):
        """Test getting status for non-existent intern."""
        result = get_intern_status(temp_db, "nonexistent")
        assert result is None

    def test_get_all_interns(self, temp_db):
        """Test getting all interns."""
        add_intern(temp_db, "i1", "Intern One", "program1")
        add_intern(temp_db, "i2", "Intern Two", "program2")

        result = get_intern_status(temp_db, None)
        assert result is not None
        assert result["total"] == 2


class TestTaskOperations:
    """Test task database operations."""

    def test_assign_task(self, temp_db):
        """Test assigning a task to an intern."""
        add_intern(temp_db, "intern-t1", "Task Tester")

        result = assign_task(
            db_path=temp_db,
            task_id="task-1",
            intern_id="intern-t1",
            title="Review documentation",
            github_issue="pulse#42"
        )
        assert result is True

    def test_update_task_status(self, temp_db):
        """Test updating task status."""
        add_intern(temp_db, "intern-t2", "Status Tester")
        assign_task(temp_db, "task-2", "intern-t2", "Test task")

        result = update_task_status(temp_db, "task-2", "in_progress")
        assert result is True

        result = update_task_status(temp_db, "task-2", "completed")
        assert result is True

    def test_update_nonexistent_task(self, temp_db):
        """Test updating a task that doesn't exist."""
        result = update_task_status(temp_db, "nonexistent", "completed")
        assert result is False


class TestQueryLogging:
    """Test query logging operations."""

    def test_log_query(self, temp_db):
        """Test logging a query."""
        # Should not raise
        log_query(
            db_path=temp_db,
            user_id="user1",
            query_type="high_priority",
            query_text="high priority issues",
            response_time_ms=150,
            success=True
        )

    def test_get_query_stats(self, temp_db):
        """Test getting query statistics."""
        # Log some queries (use_async=False for synchronous writes in tests)
        for i in range(5):
            log_query(temp_db, "user1", "summary", "summary", 100, True, use_async=False)
        for i in range(3):
            log_query(temp_db, "user2", "high_priority", "high priority", 150, True, use_async=False)

        stats = get_query_stats(temp_db)
        assert "summary" in stats
        assert stats["summary"]["count"] == 5

    def test_query_stats_empty_db(self, temp_db):
        """Test query stats on empty database."""
        stats = get_query_stats(temp_db)
        assert stats == {}


class TestAsyncDatabaseWriter:
    """Tests for async database writer."""

    @pytest.fixture
    def async_writer(self, temp_db):
        """Create and start an async writer for testing."""
        from src.bot.database import AsyncDatabaseWriter
        writer = AsyncDatabaseWriter(temp_db)
        writer.start()
        yield writer
        writer.stop()

    def test_async_writer_init(self, temp_db):
        """Test AsyncDatabaseWriter initialization."""
        from src.bot.database import AsyncDatabaseWriter

        writer = AsyncDatabaseWriter(temp_db)
        assert writer.db_path == temp_db
        assert writer.writes_queued == 0
        assert writer.writes_completed == 0
        assert writer._running is False

    def test_async_writer_start_stop(self, temp_db):
        """Test starting and stopping the async writer."""
        from src.bot.database import AsyncDatabaseWriter

        writer = AsyncDatabaseWriter(temp_db)

        # Start
        writer.start()
        assert writer._running is True
        assert writer._worker_thread is not None
        assert writer._worker_thread.is_alive()

        # Stop
        writer.stop()
        assert writer._running is False

    def test_async_writer_execute(self, async_writer, temp_db):
        """Test queueing write operations."""
        import time
        import sqlite3

        # Queue a write
        result = async_writer.execute(
            "INSERT INTO query_log (user_id, query_type, query_text, response_time_ms, success) VALUES (?, ?, ?, ?, ?)",
            ("async_user", "test", "async test query", 50, True)
        )

        assert result is True
        assert async_writer.writes_queued == 1

        # Wait for background processing
        time.sleep(0.3)

        # Verify write was completed
        assert async_writer.writes_completed == 1
        assert async_writer.writes_failed == 0

        # Verify data is in database
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM query_log WHERE user_id = ?", ("async_user",))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "async_user"

    def test_async_writer_callback(self, async_writer, temp_db):
        """Test callback is called on write completion."""
        import time

        callback_results = []

        def callback(success):
            callback_results.append(success)

        async_writer.execute(
            "INSERT INTO query_log (user_id, query_type, query_text, response_time_ms, success) VALUES (?, ?, ?, ?, ?)",
            ("callback_user", "test", "callback test", 50, True),
            callback=callback
        )

        # Wait for processing
        time.sleep(0.3)

        assert len(callback_results) == 1
        assert callback_results[0] is True

    def test_async_writer_batch_processing(self, async_writer, temp_db):
        """Test multiple writes are batched."""
        import time
        import sqlite3

        # Queue multiple writes
        for i in range(10):
            async_writer.execute(
                "INSERT INTO query_log (user_id, query_type, query_text, response_time_ms, success) VALUES (?, ?, ?, ?, ?)",
                (f"batch_user_{i}", "test", f"batch test {i}", 50, True)
            )

        assert async_writer.writes_queued == 10

        # Wait for processing
        time.sleep(0.5)

        assert async_writer.writes_completed == 10

        # Verify all rows exist
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM query_log WHERE user_id LIKE 'batch_user_%'")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 10

    def test_async_writer_stats(self, async_writer, temp_db):
        """Test writer statistics."""
        import time

        # Queue some writes
        async_writer.execute(
            "INSERT INTO query_log (user_id, query_type, query_text, response_time_ms, success) VALUES (?, ?, ?, ?, ?)",
            ("stats_user", "test", "stats test", 50, True)
        )

        time.sleep(0.3)

        stats = async_writer.get_stats()

        assert stats["queued"] == 1
        assert stats["completed"] == 1
        assert stats["failed"] == 0
        assert stats["running"] is True

    def test_log_query_async(self, temp_db):
        """Test log_query_async convenience function."""
        import time
        import sqlite3
        from src.bot.database import log_query_async, reset_async_writer

        # Reset global writer for this test
        reset_async_writer()

        # Use async logging
        log_query_async(
            temp_db,
            "async_log_user",
            "async_type",
            "async query text",
            100,
            True
        )

        # Wait for processing
        time.sleep(0.5)

        # Verify row exists
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, query_type FROM query_log WHERE user_id = ?", ("async_log_user",))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "async_log_user"
        assert row[1] == "async_type"

        # Cleanup
        reset_async_writer()
