"""
Async database writer for non-blocking write operations.

Provides a background thread-based writer for SQLite that prevents
database writes from blocking the main request thread.
"""
import logging
import os
import queue
import sqlite3
import threading
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class WriteOperation:
    """Represents a queued database write operation."""
    sql: str
    params: tuple
    callback: Optional[Callable[[bool], None]] = None


class AsyncDatabaseWriter:
    """
    Non-blocking database writer using a background thread.

    SQLite doesn't support true async, but this class provides
    non-blocking writes by queuing operations and processing
    them in a background thread. This prevents database writes
    from blocking the main request thread.

    Usage:
        writer = AsyncDatabaseWriter("/path/to/db.sqlite")
        writer.start()

        # Non-blocking write
        writer.execute("INSERT INTO logs VALUES (?, ?)", (user_id, message))

        # With callback
        writer.execute(
            "INSERT INTO logs VALUES (?, ?)",
            (user_id, message),
            callback=lambda success: print(f"Write {'succeeded' if success else 'failed'}")
        )

        # Shutdown
        writer.stop()
    """

    # Maximum queue size to prevent memory issues
    MAX_QUEUE_SIZE = 10000

    # Batch size for processing multiple writes at once
    BATCH_SIZE = 50

    def __init__(self, db_path: str, logger: logging.Logger = None):
        """
        Initialize the async database writer.

        Args:
            db_path: Path to SQLite database
            logger: Logger instance
        """
        self.db_path = db_path
        self.logger = logger or logging.getLogger("qa_agent")

        self._queue: queue.Queue[WriteOperation] = queue.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stats_lock = threading.Lock()  # Thread-safe counter access

        # Stats (protected by _stats_lock)
        self._writes_queued = 0
        self._writes_completed = 0
        self._writes_failed = 0

    @property
    def writes_queued(self) -> int:
        """Thread-safe access to queued write count."""
        with self._stats_lock:
            return self._writes_queued

    @property
    def writes_completed(self) -> int:
        """Thread-safe access to completed write count."""
        with self._stats_lock:
            return self._writes_completed

    @property
    def writes_failed(self) -> int:
        """Thread-safe access to failed write count."""
        with self._stats_lock:
            return self._writes_failed

    def _increment_queued(self) -> None:
        """Thread-safe increment of queued counter."""
        with self._stats_lock:
            self._writes_queued += 1

    def _increment_completed(self) -> None:
        """Thread-safe increment of completed counter."""
        with self._stats_lock:
            self._writes_completed += 1

    def _increment_failed(self) -> None:
        """Thread-safe increment of failed counter."""
        with self._stats_lock:
            self._writes_failed += 1

    def start(self):
        """Start the background worker thread."""
        with self._lock:
            if self._running:
                return

            self._running = True
            self._worker_thread = threading.Thread(
                target=self._process_loop,
                name="AsyncDBWriter",
                daemon=True
            )
            self._worker_thread.start()
            self.logger.debug("AsyncDatabaseWriter started")

    def stop(self, timeout: float = 5.0):
        """
        Stop the background worker thread.

        Args:
            timeout: Maximum time to wait for pending writes
        """
        with self._lock:
            if not self._running:
                return

            self._running = False

        if self._worker_thread:
            self._worker_thread.join(timeout=timeout)
            self.logger.debug(
                f"AsyncDatabaseWriter stopped. "
                f"Completed: {self.writes_completed}, Failed: {self.writes_failed}"
            )

    def execute(
        self,
        sql: str,
        params: tuple = (),
        callback: Optional[Callable[[bool], None]] = None
    ) -> bool:
        """
        Queue a write operation for async execution.

        Args:
            sql: SQL statement to execute
            params: Parameters for the SQL statement
            callback: Optional callback called with success status

        Returns:
            True if queued successfully, False if queue is full
        """
        try:
            operation = WriteOperation(sql=sql, params=params, callback=callback)
            self._queue.put_nowait(operation)
            self._increment_queued()
            return True
        except queue.Full:
            self.logger.warning("Async write queue full, dropping write operation")
            self._increment_failed()
            if callback:
                callback(False)
            return False

    def _process_loop(self):
        """Background worker that processes queued writes."""
        conn = None

        while self._running or not self._queue.empty():
            try:
                # Collect a batch of operations
                batch: list[WriteOperation] = []
                try:
                    # Wait for first item with timeout
                    first = self._queue.get(timeout=0.5)
                    batch.append(first)

                    # Try to get more items without blocking
                    while len(batch) < self.BATCH_SIZE:
                        try:
                            op = self._queue.get_nowait()
                            batch.append(op)
                        except queue.Empty:
                            break

                except queue.Empty:
                    continue

                if not batch:
                    continue

                # Process the batch
                try:
                    if conn is None:
                        conn = sqlite3.connect(self.db_path)

                    cursor = conn.cursor()

                    for op in batch:
                        try:
                            cursor.execute(op.sql, op.params)
                            if op.callback:
                                op.callback(True)
                            self._increment_completed()
                        except sqlite3.Error as e:
                            self.logger.warning(f"Async write failed: {e}")
                            if op.callback:
                                op.callback(False)
                            self._increment_failed()

                    conn.commit()

                except sqlite3.Error as e:
                    self.logger.error(f"Database error in async writer: {e}")
                    # Mark all as failed
                    for op in batch:
                        if op.callback:
                            op.callback(False)
                        self._increment_failed()
                    # Reset connection
                    if conn:
                        try:
                            conn.close()
                        except sqlite3.Error:
                            pass  # Ignore errors during cleanup
                        conn = None

            except Exception as e:
                self.logger.error(f"Unexpected error in async writer: {e}")

        # Cleanup
        if conn:
            try:
                conn.close()
            except sqlite3.Error:
                pass  # Ignore errors during cleanup

    def get_stats(self) -> dict:
        """Get writer statistics."""
        return {
            "queued": self.writes_queued,
            "completed": self.writes_completed,
            "failed": self.writes_failed,
            "pending": self._queue.qsize(),
            "running": self._running
        }


# Global async writer instance
_async_writer: Optional[AsyncDatabaseWriter] = None
_async_writer_lock = threading.Lock()


def get_async_writer(db_path: str = None) -> AsyncDatabaseWriter:
    """
    Get or create the global async database writer.

    Args:
        db_path: Path to database (only used on first call)

    Returns:
        AsyncDatabaseWriter singleton
    """
    global _async_writer

    with _async_writer_lock:
        if _async_writer is None:
            if db_path is None:
                db_path = os.environ.get("DB_PATH", "data/state.db")
            _async_writer = AsyncDatabaseWriter(db_path)
            _async_writer.start()
        return _async_writer


def reset_async_writer() -> None:
    """
    Reset the global async writer instance.

    Used for testing to ensure clean state between tests.
    """
    global _async_writer

    with _async_writer_lock:
        if _async_writer is not None:
            _async_writer.stop()
            _async_writer = None
