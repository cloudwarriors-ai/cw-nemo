"""
Real-time transcription processor for Recall.ai webhooks.

Handles incoming transcription events and stores them for later use.
"""
import json
import logging
import sqlite3
from datetime import datetime
from typing import Optional


class TranscriptionProcessor:
    """
    Process real-time transcription events from Recall.ai.

    Handles:
    - Receiving transcription webhook events
    - Storing transcript segments
    - Aggregating partial transcripts
    - Triggering notifications on keywords
    """

    # Keywords that trigger notifications
    DEFAULT_ALERT_KEYWORDS = [
        "action item",
        "todo",
        "follow up",
        "deadline",
        "urgent",
        "blocker",
        "qa bot",
    ]

    def __init__(
        self,
        db_path: str = "data/state.db",
        alert_keywords: list[str] = None,
        notification_callback=None,
        logger: logging.Logger = None
    ):
        """
        Initialize the transcription processor.

        Args:
            db_path: Path to SQLite database
            alert_keywords: Keywords that trigger notifications
            notification_callback: Function to call when keywords detected
            logger: Logger instance
        """
        self.db_path = db_path
        self.alert_keywords = [kw.lower() for kw in (alert_keywords or self.DEFAULT_ALERT_KEYWORDS)]
        self.notification_callback = notification_callback
        self.logger = logger or logging.getLogger("qa_agent")

    def process_webhook(self, data: dict) -> dict:
        """
        Process incoming transcription webhook from Recall.ai.

        Expected webhook format:
        {
            "event": "transcript.partial" | "transcript.final",
            "data": {
                "bot_id": "xxx",
                "transcript": {
                    "speaker": "John",
                    "words": [{"text": "hello", "start": 0.0, "end": 0.5}],
                    "is_final": true
                }
            }
        }

        Args:
            data: Webhook payload

        Returns:
            Processing result with any triggered alerts
        """
        event_type = data.get("event", "")
        event_data = data.get("data", {})

        bot_id = event_data.get("bot_id")
        transcript = event_data.get("transcript", {})

        if not bot_id:
            self.logger.warning("Transcription webhook missing bot_id")
            return {"status": "error", "error": "Missing bot_id"}

        # Extract transcript text
        speaker = transcript.get("speaker", "Unknown")
        words = transcript.get("words", [])
        is_final = transcript.get("is_final", False)

        text = " ".join(w.get("text", "") for w in words)
        start_time = words[0].get("start", 0) if words else 0
        end_time = words[-1].get("end", 0) if words else 0

        # Get meeting ID from bot ID
        meeting_id = self._get_meeting_id_for_bot(bot_id)

        result = {
            "status": "processed",
            "bot_id": bot_id,
            "meeting_id": meeting_id,
            "speaker": speaker,
            "text_length": len(text),
            "is_final": is_final,
            "alerts": []
        }

        # Only store final transcripts
        if is_final and meeting_id:
            self._store_segment(
                meeting_id=meeting_id,
                speaker=speaker,
                text=text,
                start_time=start_time,
                end_time=end_time
            )

            # Check for alert keywords
            alerts = self._check_keywords(text)
            if alerts:
                result["alerts"] = alerts
                self._trigger_alerts(meeting_id, speaker, text, alerts)

        return result

    def process_partial(self, bot_id: str, speaker: str, text: str) -> None:
        """
        Process a partial (non-final) transcript.

        Used for real-time display but not stored permanently.

        Args:
            bot_id: Recall.ai bot ID
            speaker: Speaker name
            text: Partial transcript text
        """
        # For now, just log partial transcripts
        self.logger.debug(f"Partial [{bot_id}] {speaker}: {text[:50]}...")

    def get_live_transcript(self, meeting_id: str, since_time: float = 0) -> list[dict]:
        """
        Get transcript segments since a given time.

        Useful for streaming updates to clients.

        Args:
            meeting_id: Meeting ID
            since_time: Only return segments after this timestamp

        Returns:
            List of transcript segments
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM transcript_segments
                WHERE meeting_id = ? AND start_time > ?
                ORDER BY start_time
            """, (meeting_id, since_time))

            segments = [dict(row) for row in cursor.fetchall()]
            conn.close()

            return segments

        except Exception as e:
            self.logger.warning(f"Failed to get live transcript: {e}")
            return []

    def get_full_transcript(self, meeting_id: str) -> list[dict]:
        """
        Get the complete transcript for a meeting.

        Args:
            meeting_id: Meeting ID

        Returns:
            All transcript segments ordered by time
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM transcript_segments
                WHERE meeting_id = ?
                ORDER BY start_time
            """, (meeting_id,))

            segments = [dict(row) for row in cursor.fetchall()]
            conn.close()

            return segments

        except Exception as e:
            self.logger.warning(f"Failed to get full transcript: {e}")
            return []

    def format_transcript(self, meeting_id: str) -> str:
        """
        Format transcript as readable text.

        Args:
            meeting_id: Meeting ID

        Returns:
            Formatted transcript string
        """
        segments = self.get_full_transcript(meeting_id)

        if not segments:
            return "No transcript available."

        lines = []
        current_speaker = None

        for segment in segments:
            speaker = segment.get("speaker", "Unknown")
            text = segment.get("text", "")

            if speaker != current_speaker:
                lines.append(f"\n[{speaker}]")
                current_speaker = speaker

            lines.append(text)

        return "\n".join(lines)

    def get_speakers(self, meeting_id: str) -> list[str]:
        """
        Get list of unique speakers in a meeting.

        Args:
            meeting_id: Meeting ID

        Returns:
            List of speaker names
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT DISTINCT speaker FROM transcript_segments
                WHERE meeting_id = ?
            """, (meeting_id,))

            speakers = [row[0] for row in cursor.fetchall()]
            conn.close()

            return speakers

        except Exception as e:
            self.logger.warning(f"Failed to get speakers: {e}")
            return []

    def search_transcript(
        self,
        meeting_id: str,
        query: str,
        speaker: str = None
    ) -> list[dict]:
        """
        Search transcript for specific text.

        Args:
            meeting_id: Meeting ID
            query: Text to search for
            speaker: Optional speaker filter

        Returns:
            Matching segments
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if speaker:
                cursor.execute("""
                    SELECT * FROM transcript_segments
                    WHERE meeting_id = ?
                    AND LOWER(text) LIKE LOWER(?)
                    AND speaker = ?
                    ORDER BY start_time
                """, (meeting_id, f"%{query}%", speaker))
            else:
                cursor.execute("""
                    SELECT * FROM transcript_segments
                    WHERE meeting_id = ?
                    AND LOWER(text) LIKE LOWER(?)
                    ORDER BY start_time
                """, (meeting_id, f"%{query}%"))

            results = [dict(row) for row in cursor.fetchall()]
            conn.close()

            return results

        except Exception as e:
            self.logger.warning(f"Failed to search transcript: {e}")
            return []

    def _store_segment(
        self,
        meeting_id: str,
        speaker: str,
        text: str,
        start_time: float,
        end_time: float
    ) -> None:
        """Store a transcript segment."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO transcript_segments
                (meeting_id, speaker, text, start_time, end_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                meeting_id,
                speaker,
                text,
                start_time,
                end_time,
                datetime.now().isoformat()
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            self.logger.warning(f"Failed to store segment: {e}")

    def _get_meeting_id_for_bot(self, bot_id: str) -> Optional[str]:
        """Look up meeting ID for a bot."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id FROM meetings WHERE bot_id = ?",
                (bot_id,)
            )
            row = cursor.fetchone()
            conn.close()

            return row[0] if row else None

        except Exception as e:
            self.logger.warning(f"Failed to get meeting ID: {e}")
            return None

    def _check_keywords(self, text: str) -> list[str]:
        """Check text for alert keywords."""
        text_lower = text.lower()
        found = []

        for keyword in self.alert_keywords:
            if keyword in text_lower:
                found.append(keyword)

        return found

    def _trigger_alerts(
        self,
        meeting_id: str,
        speaker: str,
        text: str,
        keywords: list[str]
    ) -> None:
        """Trigger notifications for detected keywords."""
        self.logger.info(
            f"Alert keywords detected in meeting {meeting_id}: {keywords}"
        )

        if self.notification_callback:
            try:
                self.notification_callback(
                    meeting_id=meeting_id,
                    speaker=speaker,
                    text=text,
                    keywords=keywords
                )
            except Exception as e:
                self.logger.error(f"Notification callback failed: {e}")
