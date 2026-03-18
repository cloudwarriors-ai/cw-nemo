"""
Meeting repository.

Handles database operations for Recall.ai meeting tracking and transcripts.
"""
import sqlite3
from datetime import datetime
from typing import Optional
import logging


class MeetingRepository:
    """
    Repository for meeting and transcript data access.

    Provides operations for meetings and transcript segments.
    """

    def __init__(
        self,
        db_path: str,
        logger: Optional[logging.Logger] = None
    ):
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)

    def get_by_id(self, meeting_id: str) -> Optional[dict]:
        """
        Get a meeting by ID.

        Args:
            meeting_id: Meeting ID

        Returns:
            Meeting record or None if not found
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, bot_id, meeting_url, requested_by, channel_id,
                       status, created_at, updated_at, ended_at
                FROM meetings
                WHERE id = ?
            """, (meeting_id,))

            row = cursor.fetchone()
            conn.close()

            return dict(row) if row else None

        except Exception as e:
            self.logger.warning(f"Failed to get meeting: {e}")
            return None

    def get_transcript(self, meeting_id: str) -> Optional[dict]:
        """
        Get transcript and metadata for a meeting.

        Args:
            meeting_id: Meeting ID

        Returns:
            Dictionary with transcript, participants, date, duration.
            None if meeting not found.
        """
        try:
            conn = sqlite3.connect(self.db_path)
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
            self.logger.warning(f"Failed to get meeting transcript: {e}")
            return None

    def create(
        self,
        meeting_id: str,
        bot_id: str,
        meeting_url: str,
        requested_by: Optional[str] = None,
        channel_id: Optional[str] = None
    ) -> bool:
        """
        Create a new meeting record.

        Args:
            meeting_id: Unique meeting ID
            bot_id: Recall.ai bot ID
            meeting_url: URL of the meeting
            requested_by: User who requested the bot
            channel_id: Channel where requested

        Returns:
            True if created successfully
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO meetings
                (id, bot_id, meeting_url, requested_by, channel_id, status)
                VALUES (?, ?, ?, ?, ?, 'joining')
            """, (meeting_id, bot_id, meeting_url, requested_by, channel_id))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            self.logger.error(f"Failed to create meeting: {e}")
            return False

    def update_status(
        self,
        meeting_id: str,
        status: str,
        ended_at: Optional[str] = None
    ) -> bool:
        """
        Update meeting status.

        Args:
            meeting_id: Meeting ID
            status: New status
            ended_at: Optional end timestamp

        Returns:
            True if updated
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if ended_at:
                cursor.execute("""
                    UPDATE meetings
                    SET status = ?, updated_at = ?, ended_at = ?
                    WHERE id = ?
                """, (status, datetime.now().isoformat(), ended_at, meeting_id))
            else:
                cursor.execute("""
                    UPDATE meetings
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                """, (status, datetime.now().isoformat(), meeting_id))

            updated = cursor.rowcount > 0
            conn.commit()
            conn.close()

            return updated

        except Exception as e:
            self.logger.warning(f"Failed to update meeting status: {e}")
            return False

    def add_transcript_segment(
        self,
        meeting_id: str,
        speaker: str,
        text: str,
        start_time: float,
        end_time: Optional[float] = None
    ) -> bool:
        """
        Add a transcript segment.

        Args:
            meeting_id: Meeting ID
            speaker: Speaker name
            text: Spoken text
            start_time: Start time in seconds
            end_time: Optional end time in seconds

        Returns:
            True if added
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO transcript_segments
                (meeting_id, speaker, text, start_time, end_time)
                VALUES (?, ?, ?, ?, ?)
            """, (meeting_id, speaker, text, start_time, end_time))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            self.logger.warning(f"Failed to add transcript segment: {e}")
            return False

    def get_by_status(self, status: str) -> list[dict]:
        """
        Get meetings by status.

        Args:
            status: Meeting status to filter by

        Returns:
            List of meeting records
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, bot_id, meeting_url, requested_by, channel_id,
                       status, created_at, updated_at, ended_at
                FROM meetings
                WHERE status = ?
                ORDER BY created_at DESC
            """, (status,))

            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            self.logger.warning(f"Failed to get meetings by status: {e}")
            return []

    def get_recent(self, limit: int = 10) -> list[dict]:
        """
        Get recent meetings.

        Args:
            limit: Maximum number to return

        Returns:
            List of meeting records
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, bot_id, meeting_url, requested_by, channel_id,
                       status, created_at, updated_at, ended_at
                FROM meetings
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            self.logger.warning(f"Failed to get recent meetings: {e}")
            return []
