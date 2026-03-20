"""
Meeting handler for managing meeting lifecycle and events.

Coordinates between Recall.ai client, database, and notifications.
"""
from collections import OrderedDict
import json
import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from typing import Optional, Tuple

from .recall_client import RecallClient, BotStatus
from .wake_word_detector import WakeWordDetector


class MeetingHandler:
    """
    Handle meeting lifecycle from join request to completion.

    Manages:
    - Creating bots for meetings
    - Tracking meeting state in database
    - Processing meeting completion
    - Generating meeting notes
    - Voice responses to meeting transcription
    """

    # Debounce settings for voice responses
    VOICE_DEBOUNCE_SECONDS = 1.0

    def __init__(
        self,
        recall_client: RecallClient,
        db_path: str = "data/state.db",
        voice_pipeline=None,
        avatar_session_manager=None,
        bot_name: str = "QA Bot",
        logger: logging.Logger = None
    ):
        """
        Initialize the meeting handler.

        Args:
            recall_client: Recall.ai client instance
            db_path: Path to SQLite database
            voice_pipeline: Optional voice pipeline for voice responses
            avatar_session_manager: Optional avatar session manager for Simli integration
            bot_name: Bot name for speaker filtering
            logger: Logger instance
        """
        self.recall = recall_client
        self.db_path = db_path
        self.voice_pipeline = voice_pipeline
        self._avatar_session_manager = avatar_session_manager
        self.bot_name = bot_name
        self.logger = logger or logging.getLogger("qa_agent")

        # Voice response debounce state
        self._voice_debounce: dict[str, float] = {}
        self._debounce_lock = threading.Lock()

        # Map Recall bot_id -> audio_bot_id (for WebSocket routing)
        self._audio_bot_id_map: dict[str, str] = {}

        # Map Recall bot_id -> LiveKit room name (for Simli avatar routing)
        self._livekit_room_map: dict[str, str] = {}

        # Conversation history per meeting for context-aware responses
        # Format: {meeting_id: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
        # Uses OrderedDict for LRU eviction when max meetings reached
        self._conversation_history: OrderedDict[str, list] = OrderedDict()
        self._history_lock = threading.Lock()
        self.MAX_HISTORY_TURNS = 10  # Keep last 10 exchanges per meeting
        self._MAX_CONVERSATION_MEETINGS = 500  # Max concurrent meeting histories

        # Wake word detector for voice commands
        self._wake_word_detector = WakeWordDetector(bot_name=bot_name)

    def join_meeting(
        self,
        meeting_url: str,
        requested_by: str,
        channel_id: str = None,
        bot_name: str = None,
        output_media_url: str = None,
        variant: str = None,
        audio_bot_id: str = None,
        livekit_room: str = None
    ) -> dict:
        """
        Request bot to join a meeting.

        Args:
            meeting_url: Zoom/Teams/Meet URL
            requested_by: User who requested the bot
            channel_id: Zoom channel to post updates to
            bot_name: Custom bot name for this meeting
            output_media_url: URL of avatar webpage for Output Media
            variant: Bot variant (web_gpu for avatar support)
            audio_bot_id: Bot ID used in avatar page URL for WebSocket routing
            livekit_room: LiveKit room name for Simli avatar (routes through LiveKit)

        Returns:
            Dict with meeting_id, bot_id, and status
        """
        meeting_id = str(uuid.uuid4())[:12]

        try:
            # Create bot via Recall.ai
            bot_response = self.recall.create_bot(
                meeting_url=meeting_url,
                bot_name=bot_name,
                output_media_url=output_media_url,
                variant=variant
            )

            bot_id = bot_response.get("id")

            # Store audio bot ID mapping for WebSocket routing
            if audio_bot_id and bot_id:
                self._audio_bot_id_map[bot_id] = audio_bot_id
                self.logger.info(f"Mapped Recall bot {bot_id} -> audio bot {audio_bot_id}")

            # Store LiveKit room mapping for Simli avatar routing
            if livekit_room and bot_id:
                self._livekit_room_map[bot_id] = livekit_room
                self.logger.info(f"Mapped Recall bot {bot_id} -> LiveKit room {livekit_room}")

            # Council fix: Add WebSocket ID mapping for avatar routing
            if bot_id:
                try:
                    from ..avatar.websocket_manager import get_avatar_ws_manager
                    ws_manager = get_avatar_ws_manager(self.logger)
                    ws_manager.add_id_mapping(meeting_id, bot_id)
                    self.logger.debug(f"Added WebSocket ID mapping: {meeting_id} <-> {bot_id}")
                except ImportError:
                    pass

            # Store meeting record
            self._store_meeting(
                meeting_id=meeting_id,
                bot_id=bot_id,
                meeting_url=meeting_url,
                requested_by=requested_by,
                channel_id=channel_id
            )

            # Council fix: Start avatar session when output_media_url is configured
            avatar_started = False
            if output_media_url and self._avatar_session_manager:
                try:
                    avatar_started = self._avatar_session_manager.start_session(meeting_id)
                    if avatar_started:
                        self.logger.info(f"Avatar session started for meeting {meeting_id}")
                    else:
                        self.logger.warning(f"Failed to start avatar session for {meeting_id}")
                except Exception as e:
                    self.logger.error(f"Avatar session error: {e}")

            self.logger.info(f"Meeting {meeting_id} created, bot {bot_id} joining")

            return {
                "meeting_id": meeting_id,
                "bot_id": bot_id,
                "status": "joining",
                "message": "Bot is joining the meeting...",
                "avatar_started": avatar_started
            }

        except ValueError as e:
            # Invalid meeting URL
            self.logger.warning(f"Invalid meeting URL: {e}")
            return {
                "meeting_id": meeting_id,
                "status": "error",
                "error": str(e)
            }

        except Exception as e:
            self.logger.error(f"Failed to join meeting: {e}")
            return {
                "meeting_id": meeting_id,
                "status": "error",
                "error": "Failed to create meeting bot"
            }

    def get_meeting_status(self, meeting_id: str) -> Optional[dict]:
        """
        Get current status of a meeting.

        Args:
            meeting_id: Meeting ID

        Returns:
            Meeting details with current status, or None if not found
        """
        meeting = self._get_meeting(meeting_id)
        if not meeting:
            return None

        # Get live status from Recall.ai if bot is active
        if meeting["status"] not in ("completed", "error"):
            try:
                bot_status = self.recall.get_bot_status(meeting["bot_id"])
                meeting["bot_status"] = bot_status.value

                # Update status based on bot state
                if bot_status == BotStatus.RECORDING:
                    meeting["status"] = "recording"
                elif bot_status == BotStatus.IN_CALL:
                    meeting["status"] = "in_call"
                elif bot_status == BotStatus.IN_WAITING_ROOM:
                    meeting["status"] = "waiting"
                elif bot_status == BotStatus.DONE:
                    meeting["status"] = "completed"
                    self._update_meeting_status(meeting_id, "completed")

            except Exception as e:
                self.logger.warning(f"Could not get bot status: {e}")

        return meeting

    def leave_meeting(self, meeting_id: str) -> dict:
        """
        Make the bot leave a meeting.

        Args:
            meeting_id: Meeting ID

        Returns:
            Result of leave operation
        """
        meeting = self._get_meeting(meeting_id)
        if not meeting:
            return {"status": "error", "error": "Meeting not found"}

        try:
            self.recall.leave_meeting(meeting["bot_id"])
            self._update_meeting_status(meeting_id, "left")

            return {
                "meeting_id": meeting_id,
                "status": "left",
                "message": "Bot has left the meeting"
            }

        except Exception as e:
            self.logger.error(f"Failed to leave meeting: {e}")
            return {"status": "error", "error": str(e)}

    def get_transcript(self, meeting_id: str) -> Optional[dict]:
        """
        Get transcript for a meeting.

        Args:
            meeting_id: Meeting ID

        Returns:
            Transcript data or None if not available
        """
        meeting = self._get_meeting(meeting_id)
        if not meeting:
            return None

        # Check if we have cached transcript
        cached = self._get_cached_transcript(meeting_id)
        if cached:
            return cached

        # Fetch from Recall.ai
        try:
            segments = self.recall.get_transcript(meeting["bot_id"])

            transcript = {
                "meeting_id": meeting_id,
                "segments": segments,
                "segment_count": len(segments),
                "fetched_at": datetime.now().isoformat()
            }

            # Cache the transcript
            self._cache_transcript(meeting_id, transcript)

            return transcript

        except Exception as e:
            self.logger.error(f"Failed to get transcript: {e}")
            return None

    def get_meeting_notes(self, meeting_id: str) -> Optional[str]:
        """
        Generate meeting notes from transcript.

        Args:
            meeting_id: Meeting ID

        Returns:
            Formatted meeting notes or None
        """
        transcript = self.get_transcript(meeting_id)
        if not transcript:
            return None

        meeting = self._get_meeting(meeting_id)
        segments = transcript.get("segments", [])

        if not segments:
            return "No transcript available for this meeting."

        # Format basic meeting notes
        notes = []
        notes.append(f"# Meeting Notes")
        notes.append(f"**Meeting ID:** {meeting_id}")
        notes.append(f"**Date:** {meeting.get('created_at', 'Unknown')}")
        notes.append(f"**Requested by:** {meeting.get('requested_by', 'Unknown')}")
        notes.append("")
        notes.append("## Transcript")
        notes.append("")

        current_speaker = None
        for segment in segments:
            speaker = segment.get("speaker", "Unknown")
            text = segment.get("text", "")

            if speaker != current_speaker:
                notes.append(f"\n**{speaker}:**")
                current_speaker = speaker

            notes.append(text)

        return "\n".join(notes)

    def list_meetings(
        self,
        status: str = None,
        requested_by: str = None,
        limit: int = 20
    ) -> list[dict]:
        """
        List meetings with optional filtering.

        Args:
            status: Filter by status
            requested_by: Filter by requester
            limit: Max results

        Returns:
            List of meeting records
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM meetings WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)

            if requested_by:
                query += " AND requested_by = ?"
                params.append(requested_by)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            meetings = [dict(row) for row in cursor.fetchall()]
            conn.close()

            return meetings

        except Exception as e:
            self.logger.warning(f"Failed to list meetings: {e}")
            return []

    def cleanup_completed(self, days_old: int = 30) -> int:
        """
        Clean up old completed meeting records.

        Args:
            days_old: Delete meetings older than this many days

        Returns:
            Number of records deleted
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM meetings
                WHERE status = 'completed'
                AND created_at < datetime('now', ?)
            """, (f"-{days_old} days",))

            deleted = cursor.rowcount

            cursor.execute("""
                DELETE FROM transcripts
                WHERE meeting_id NOT IN (SELECT id FROM meetings)
            """)

            conn.commit()
            conn.close()

            self.logger.info(f"Cleaned up {deleted} old meeting records")
            return deleted

        except Exception as e:
            self.logger.error(f"Cleanup failed: {e}")
            return 0

    def _store_meeting(
        self,
        meeting_id: str,
        bot_id: str,
        meeting_url: str,
        requested_by: str,
        channel_id: str = None
    ) -> None:
        """Store a new meeting record."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO meetings
                (id, bot_id, meeting_url, requested_by, channel_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                meeting_id,
                bot_id,
                meeting_url,
                requested_by,
                channel_id,
                "joining",
                datetime.now().isoformat()
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            self.logger.error(f"Failed to store meeting: {e}")

    def _get_meeting(self, meeting_id: str) -> Optional[dict]:
        """Get meeting record by ID."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,))
            row = cursor.fetchone()
            conn.close()

            return dict(row) if row else None

        except Exception as e:
            self.logger.warning(f"Failed to get meeting: {e}")
            return None

    def _update_meeting_status(self, meeting_id: str, status: str) -> None:
        """Update meeting status and trigger cleanup for terminal states."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE meetings
                SET status = ?, updated_at = ?
                WHERE id = ?
            """, (status, datetime.now().isoformat(), meeting_id))

            conn.commit()
            conn.close()

            # Cleanup for terminal states
            if status in ("completed", "left", "error", "abandoned"):
                self._cleanup_meeting_resources(meeting_id)

        except Exception as e:
            self.logger.warning(f"Failed to update meeting status: {e}")

    def _cleanup_meeting_resources(self, meeting_id: str) -> None:
        """
        Clean up resources when a meeting ends.

        Clears conversation history, avatar sessions, and LiveKit rooms.
        """
        self.logger.info(f"Cleaning up resources for meeting {meeting_id}")

        # Clear conversation history
        self.clear_conversation(meeting_id)

        # Cleanup avatar session if present
        if self._avatar_session_manager:
            try:
                self._avatar_session_manager.cleanup_session(meeting_id)
            except Exception as e:
                self.logger.warning(f"Avatar session cleanup failed: {e}")

        # Stop LiveKit agent for this meeting's room
        try:
            from ..avatar.livekit_manager import get_livekit_manager
            livekit_manager = get_livekit_manager()
            room_name = livekit_manager.get_room_for_meeting(meeting_id)
            if room_name:
                livekit_manager.delete_room(room_name)
                self.logger.info(f"Deleted LiveKit room {room_name} for meeting {meeting_id}")
        except Exception as e:
            self.logger.debug(f"LiveKit cleanup skipped: {e}")

    def _get_cached_transcript(self, meeting_id: str) -> Optional[dict]:
        """Get cached transcript for a meeting."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM transcripts WHERE meeting_id = ?",
                (meeting_id,)
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                return {
                    "meeting_id": meeting_id,
                    "segments": json.loads(row["segments"]),
                    "fetched_at": row["fetched_at"]
                }
            return None

        except Exception as e:
            self.logger.warning(f"Failed to get cached transcript: {e}")
            return None

    def _cache_transcript(self, meeting_id: str, transcript: dict) -> None:
        """Cache transcript for a meeting."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO transcripts
                (meeting_id, segments, fetched_at)
                VALUES (?, ?, ?)
            """, (
                meeting_id,
                json.dumps(transcript.get("segments", [])),
                transcript.get("fetched_at")
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            self.logger.warning(f"Failed to cache transcript: {e}")

    def _get_meeting_by_bot_id(self, bot_id: str) -> Optional[dict]:
        """Get meeting record by bot ID."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM meetings WHERE bot_id = ?", (bot_id,))
            row = cursor.fetchone()
            conn.close()

            return dict(row) if row else None

        except Exception as e:
            self.logger.warning(f"Failed to get meeting by bot_id: {e}")
            return None

    def _get_active_meeting(self) -> Optional[dict]:
        """Get the most recent active/recording meeting as fallback."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM meetings
                WHERE status IN ('recording', 'in_call', 'joining', 'running', 'in_call_recording', 'in_call_not_recording', 'processing')
                ORDER BY created_at DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            conn.close()

            return dict(row) if row else None

        except Exception as e:
            self.logger.warning(f"Failed to get active meeting: {e}")
            return None

    def cleanup_abandoned(self, stale_minutes: int = 30) -> int:
        """
        Mark stale meetings as abandoned.

        Meetings in 'joining' or 'waiting' status for too long
        are marked as 'abandoned'.

        Args:
            stale_minutes: Minutes before considering abandoned

        Returns:
            Number of meetings marked as abandoned
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cutoff = datetime.now().isoformat()

            # Find meetings stuck in joining/waiting states
            cursor.execute("""
                UPDATE meetings
                SET status = 'abandoned', updated_at = ?
                WHERE status IN ('joining', 'waiting')
                AND datetime(created_at) < datetime('now', ?)
            """, (cutoff, f"-{stale_minutes} minutes"))

            abandoned = cursor.rowcount
            conn.commit()
            conn.close()

            if abandoned > 0:
                self.logger.info(f"Marked {abandoned} stale meetings as abandoned")

            return abandoned

        except Exception as e:
            self.logger.error(f"Cleanup abandoned failed: {e}")
            return 0

    def handle_status_update(
        self,
        bot_id: str,
        status: str,
        data: dict = None
    ) -> None:
        """
        Handle bot status update from Recall.ai webhook.

        Args:
            bot_id: The Recall.ai bot ID
            status: New status string
            data: Additional webhook data
        """
        # Find meeting by bot_id
        meeting = self._get_meeting_by_bot_id(bot_id)
        if meeting:
            # Map Recall.ai status to our internal status
            status_map = {
                "joining": "joining",
                "in_waiting_room": "waiting",
                "in_call_not_recording": "in_call",
                "in_call_recording": "recording",
                "call_ended": "completed",
                "done": "completed",
                "fatal": "error",
            }
            internal_status = status_map.get(status, status)
            self._update_meeting_status(meeting["id"], internal_status)
            self.logger.info(f"Meeting {meeting['id']} status: {status} -> {internal_status}")
        else:
            self.logger.warning(f"No meeting found for bot_id: {bot_id}")

    def handle_transcription(self, data: dict) -> None:
        """
        Handle real-time transcription from Recall.ai webhook.

        Args:
            data: Webhook payload with transcription data
        """
        self.logger.debug(f"Transcription payload: {json.dumps(data, default=str)[:500]}")

        # Extract bot_id and transcript data from webhook
        bot_id = self._extract_bot_id(data)
        transcript_data = self._extract_transcript_data(data)

        # Find meeting by bot_id or fallback to active meeting
        meeting = self._find_meeting_for_transcript(bot_id)
        if not meeting:
            self.logger.warning(f"No meeting found for transcription bot_id: {bot_id}")
            return

        meeting_id = meeting["id"]
        self.logger.debug(f"Processing transcript for meeting: {meeting_id}")

        # Parse transcript segment from data
        segment = self._parse_transcript_segment(transcript_data)
        if not segment or not segment.get("text"):
            return

        # Store the segment
        self._append_transcript_segment(meeting_id, segment)
        self.logger.info(f"Stored transcript: [{segment['speaker']}] {segment['text'][:50]}...")

        # Check for voice response trigger
        self._check_voice_trigger(meeting, segment)

    def _extract_bot_id(self, data: dict) -> Optional[str]:
        """
        Extract bot_id from multiple possible locations in Recall.ai webhooks.

        Supports formats:
        - { "bot_id": "..." }
        - { "data": { "bot_id": "..." } }
        - { "recording": { "bot_id": "..." } }

        Args:
            data: Webhook payload

        Returns:
            Bot ID or None if not found
        """
        bot_id = data.get("bot_id")
        if bot_id:
            return bot_id

        nested_data = data.get("data", {})
        if isinstance(nested_data, dict):
            bot_id = nested_data.get("bot_id")
            if bot_id:
                return bot_id

        recording = data.get("recording", {})
        if isinstance(recording, dict):
            return recording.get("bot_id")

        return None

    def _extract_transcript_data(self, data: dict) -> dict:
        """
        Extract transcript data from multiple possible webhook formats.

        Recall.ai uses various structures:
        - {"transcript": {"words": [...]}}
        - {"data": {"transcript": {"words": [...]}}}
        - {"data": {"data": {"words": [...]}}}
        - {"data": {"words": [...]}}
        - {"words": [...]}

        Args:
            data: Webhook payload

        Returns:
            Dict containing transcript data with words/text/speaker
        """
        self.logger.debug(f"Raw webhook data keys: {list(data.keys())}")

        # Check each possible location for 'words' key
        locations = [
            ("transcript", data.get("transcript", {})),
            ("data.transcript", data.get("data", {}).get("transcript", {})),
            ("data.data", data.get("data", {}).get("data", {})),
            ("data", data.get("data", {})),
            ("root", data),
        ]

        for location_name, candidate in locations:
            if isinstance(candidate, dict) and candidate.get("words"):
                self.logger.debug(f"Found words in: {location_name}")
                return candidate

        # Fallback: use data.data or data even without words
        nested = data.get("data", {}).get("data", {})
        if nested and isinstance(nested, dict):
            self.logger.debug("Using data.data as fallback (no words found)")
            return nested

        fallback = data.get("data", {})
        if isinstance(fallback, dict):
            self.logger.debug("Using data as fallback (no words found)")
            return fallback

        return {}

    def _find_meeting_for_transcript(self, bot_id: Optional[str]) -> Optional[dict]:
        """
        Find the meeting for a transcript webhook.

        First tries to find by bot_id, then falls back to most recent active meeting.

        Args:
            bot_id: Bot ID from webhook

        Returns:
            Meeting record or None
        """
        meeting = None
        if bot_id:
            meeting = self._get_meeting_by_bot_id(bot_id)

        if not meeting:
            meeting = self._get_active_meeting()
            if meeting:
                self.logger.debug(f"Using active meeting fallback: {meeting['id']}")

        return meeting

    def _parse_transcript_segment(self, transcript_data: dict) -> dict:
        """
        Parse a transcript segment from webhook data.

        Extracts speaker, text, and timestamps from Recall.ai format.

        Args:
            transcript_data: Dict containing words/text/participant

        Returns:
            Dict with speaker, text, start_time, end_time
        """
        words = transcript_data.get("words", [])
        participant = transcript_data.get("participant", {})
        speaker = participant.get("name") or transcript_data.get("speaker", "Unknown")
        text = transcript_data.get("text", "")

        # Extract text from words array if no direct text
        if not text and words:
            text = " ".join(w.get("text", "") for w in words)

        # Get timestamps from words array
        start_time = 0
        end_time = 0
        if words:
            first_word = words[0]
            last_word = words[-1]
            start_ts = first_word.get("start_timestamp", {})
            end_ts = last_word.get("end_timestamp", {})
            start_time = start_ts.get("relative", 0)
            end_time = end_ts.get("relative", 0)

        self.logger.debug(f"Extracted: speaker={speaker}, text={text[:50] if text else 'EMPTY'}, words={len(words)}")

        return {
            "speaker": speaker,
            "text": text,
            "start_time": start_time,
            "end_time": end_time,
        }

    def _check_voice_trigger(self, meeting: dict, segment: dict) -> None:
        """
        Check if this segment should trigger a voice response.

        Args:
            meeting: Meeting record
            segment: Parsed transcript segment
        """
        if not self.voice_pipeline:
            return

        meeting_id = meeting["id"]
        text = segment.get("text", "")
        speaker = segment.get("speaker", "")

        self.logger.debug(f"Voice pipeline check: pipeline={self.voice_pipeline is not None}")
        should_respond, query = self._should_respond_voice(text, speaker)
        self.logger.debug(f"Voice check: should_respond={should_respond}, query={query[:50] if query else 'empty'}")

        if should_respond and self._check_debounce(meeting_id):
            recall_bot_id = meeting.get("bot_id")
            ws_bot_id = self._audio_bot_id_map.get(recall_bot_id, recall_bot_id)
            livekit_room = self._livekit_room_map.get(recall_bot_id)
            self.logger.debug(f"Voice trigger: recall_bot={recall_bot_id}, ws_bot={ws_bot_id}, livekit_room={livekit_room}")
            if ws_bot_id:
                self._trigger_voice_response(query, ws_bot_id, meeting_id, recall_bot_id, livekit_room)

    def _append_transcript_segment(
        self,
        meeting_id: str,
        segment: dict
    ) -> None:
        """Append a segment to the cached transcript."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Insert segment into transcript_segments table
            cursor.execute("""
                INSERT INTO transcript_segments
                (meeting_id, speaker, text, start_time, end_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                meeting_id,
                segment.get("speaker", "Unknown"),
                segment.get("text", ""),
                segment.get("start_time", 0),
                segment.get("end_time", 0),
                datetime.now().isoformat()
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            self.logger.warning(f"Failed to append transcript segment: {e}")

    # =========================================================================
    # Voice Response Methods
    # =========================================================================

    def _should_respond_voice(self, text: str, speaker: str) -> Tuple[bool, str]:
        """
        Check if we should respond to this transcription with voice.

        Delegates wake word detection to WakeWordDetector, but adds
        additional filtering for "Unknown" speaker during debounce.

        Args:
            text: Transcribed text
            speaker: Speaker name

        Returns:
            Tuple of (should_respond, extracted_query)
        """
        # Also ignore "Unknown" speaker during debounce period
        # This catches the bot's own voice being transcribed back
        speaker_lower = speaker.lower()
        if speaker_lower == 'unknown':
            with self._debounce_lock:
                now = time.time()
                for meeting_id, last_time in self._voice_debounce.items():
                    if now - last_time < self.VOICE_DEBOUNCE_SECONDS + 30:  # Extra 30s buffer
                        self.logger.debug(f"Ignoring 'Unknown' speaker during bot speech cooldown")
                        return False, ""

        # Delegate to wake word detector
        detected, query = self._wake_word_detector.detect(text, speaker)
        if detected:
            self.logger.debug(f"Voice wake word detected, query: {query[:50]}")
        return detected, query

    def _check_debounce(self, meeting_id: str) -> bool:
        """
        Check if enough time has passed since last voice response.

        Args:
            meeting_id: Meeting to check

        Returns:
            True if we can respond, False if still in debounce period
        """
        with self._debounce_lock:
            now = time.time()
            last_response = self._voice_debounce.get(meeting_id, 0)

            if now - last_response < self.VOICE_DEBOUNCE_SECONDS:
                self.logger.debug(f"Voice response debounced for {meeting_id}")
                return False

            # Update last response time
            self._voice_debounce[meeting_id] = now
            return True

    def _trigger_voice_response(
        self,
        query: str,
        ws_bot_id: str,
        meeting_id: str,
        recall_bot_id: str = None,
        livekit_room: str = None
    ) -> None:
        """
        Trigger voice response in background thread.

        Args:
            query: User's query text
            ws_bot_id: Bot ID for WebSocket routing (avatar page)
            meeting_id: Meeting ID for logging
            recall_bot_id: Recall.ai bot ID for audio output to Zoom
            livekit_room: LiveKit room name for Simli avatar (routes through LiveKit)
        """
        if not self.voice_pipeline:
            return

        def _respond():
            try:
                start_time = time.time()
                self.logger.info(f"Voice response triggered for: {query[:50]}...")
                if livekit_room:
                    self.logger.info(f"Routing through LiveKit room: {livekit_room}")

                # Get conversation history for context-aware responses
                conversation_history = self.get_conversation_history(meeting_id)
                self.logger.debug(f"Passing {len(conversation_history)} history messages for meeting {meeting_id}")

                # Callback to store the exchange in conversation history
                def on_response(user_query: str, assistant_response: str):
                    self.add_to_conversation(meeting_id, user_query, assistant_response)
                    self.logger.info(f"Stored conversation: Q='{user_query[:50]}...' A='{assistant_response[:50]}...'")

                # Use voice pipeline to respond - pass both bot IDs, conversation history, and LiveKit room
                self.voice_pipeline.respond_to_query(
                    query,
                    ws_bot_id,
                    recall_bot_id=recall_bot_id,
                    conversation_history=conversation_history,
                    on_response=on_response,
                    livekit_room=livekit_room
                )

                latency = (time.time() - start_time) * 1000
                self.logger.info(f"Voice response completed in {latency:.0f}ms")

            except Exception as e:
                self.logger.error(f"Voice response error: {e}", exc_info=True)

        # Run in background to not block webhook
        thread = threading.Thread(target=_respond, daemon=True)
        thread.start()

    def get_conversation_history(self, meeting_id: str) -> list:
        """Get conversation history for a meeting."""
        with self._history_lock:
            return self._conversation_history.get(meeting_id, []).copy()

    def add_to_conversation(self, meeting_id: str, user_query: str, assistant_response: str):
        """Add a query/response pair to meeting conversation history.

        Memory safety: Bounded to _MAX_CONVERSATION_MEETINGS entries.
        Uses LRU eviction (oldest meetings removed first) when limit reached.
        """
        with self._history_lock:
            # Evict oldest meetings if at capacity
            while len(self._conversation_history) >= self._MAX_CONVERSATION_MEETINGS:
                oldest_meeting_id, _ = self._conversation_history.popitem(last=False)
                self.logger.debug(f"Evicted conversation history for {oldest_meeting_id}")

            if meeting_id not in self._conversation_history:
                self._conversation_history[meeting_id] = []
            else:
                # Move to end (most recently used)
                self._conversation_history.move_to_end(meeting_id)

            history = self._conversation_history[meeting_id]
            history.append({"role": "user", "content": user_query})
            history.append({"role": "assistant", "content": assistant_response})

            # Trim to max turns (each turn = 2 messages)
            max_messages = self.MAX_HISTORY_TURNS * 2
            if len(history) > max_messages:
                self._conversation_history[meeting_id] = history[-max_messages:]

            self.logger.debug(f"Conversation history for {meeting_id}: {len(self._conversation_history[meeting_id])} messages")

    def clear_conversation(self, meeting_id: str):
        """Clear conversation history for a meeting (e.g., when meeting ends)."""
        with self._history_lock:
            if meeting_id in self._conversation_history:
                del self._conversation_history[meeting_id]
                self.logger.debug(f"Cleared conversation history for {meeting_id}")
