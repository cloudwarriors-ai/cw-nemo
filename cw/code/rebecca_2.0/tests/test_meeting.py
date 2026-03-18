"""
Tests for meeting integration (Phase 3 - Recall.ai).

Tests:
- Recall.ai client
- Meeting handler
- Transcription processor
- API endpoints
"""
import json
import pytest
import sqlite3
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from src.meeting.recall_client import RecallClient, BotStatus
from src.meeting.meeting_handler import MeetingHandler
from src.meeting.transcription import TranscriptionProcessor


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def auth_headers():
    """Return headers with API key for authenticated requests."""
    import os
    api_key = os.environ.get("API_KEY", "test-api-key")
    return {
        "Content-Type": "application/json",
        "X-API-Key": api_key
    }


@pytest.fixture
def recall_client():
    """Create a RecallClient for testing."""
    return RecallClient(
        api_key="test-api-key",
        bot_name="Test Bot",
        bot_image_url="https://example.com/avatar.png",
        transcription_webhook_url="https://example.com/webhook"
    )


@pytest.fixture
def meeting_handler(tmp_path):
    """Create a MeetingHandler for testing."""
    db_path = str(tmp_path / "test.db")
    _init_test_db(db_path)

    recall_client = Mock(spec=RecallClient)
    recall_client.create_bot.return_value = {"id": "bot-123"}
    recall_client.get_bot_status.return_value = BotStatus.IN_CALL
    recall_client.get_transcript.return_value = [
        {"speaker": "John", "text": "Hello", "start_time": 0.0, "end_time": 1.0}
    ]

    return MeetingHandler(
        recall_client=recall_client,
        db_path=db_path
    )


@pytest.fixture
def transcription_processor(tmp_path):
    """Create a TranscriptionProcessor for testing."""
    db_path = str(tmp_path / "test.db")
    _init_test_db(db_path)
    return TranscriptionProcessor(db_path=db_path)


@pytest.fixture
def app_with_meeting(tmp_path):
    """Create Flask app with meeting integration enabled."""
    import os
    from src.bot.app import create_app

    db_path = str(tmp_path / "test.db")
    _init_test_db(db_path)

    # Get API key from environment (set in conftest.py)
    api_key = os.environ.get("API_KEY", "test-api-key")

    app = create_app({
        "TESTING": True,
        "DB_PATH": db_path,
        "RECALL_API_KEY": "test-key",
        "RECALL_BOT_NAME": "Test Bot",
        "RECALL_TRANSCRIPTION_SECRET": "test-secret",
        "API_KEY": api_key,
    })

    # Mock the recall client
    mock_recall = Mock(spec=RecallClient)
    mock_recall.create_bot.return_value = {"id": "bot-123"}
    mock_recall.get_bot_status.return_value = BotStatus.IN_CALL
    mock_recall.leave_meeting.return_value = {}
    mock_recall.get_transcript.return_value = []

    if app.meeting_handler:
        app.meeting_handler.recall = mock_recall

    return app


def _init_test_db(db_path: str):
    """Initialize test database with required tables."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Meetings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY,
            bot_id TEXT NOT NULL,
            meeting_url TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            channel_id TEXT,
            status TEXT DEFAULT 'joining',
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # Transcripts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            meeting_id TEXT PRIMARY KEY,
            segments TEXT,
            fetched_at TEXT
        )
    """)

    # Transcript segments table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transcript_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT NOT NULL,
            speaker TEXT,
            text TEXT,
            start_time REAL,
            end_time REAL,
            created_at TEXT
        )
    """)

    # Interns table for dependencies
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            status TEXT DEFAULT 'onboarding',
            program TEXT,
            supervisor TEXT,
            start_date TEXT,
            end_date TEXT,
            created_at TEXT,
            updated_at TEXT,
            notes TEXT
        )
    """)

    # Rate limits table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)

    # Meeting rate limits table (for council fix)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meeting_rate_limits (
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# RecallClient Tests
# ============================================================

class TestRecallClient:
    """Tests for RecallClient."""

    def test_init(self, recall_client):
        """Test client initialization."""
        assert recall_client.api_key == "test-api-key"
        assert recall_client.bot_name == "Test Bot"
        assert recall_client.transcription_webhook_url == "https://example.com/webhook"

    @patch("requests.request")
    def test_create_bot_success(self, mock_request, recall_client):
        """Test successful bot creation."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "bot-abc", "status": "ready"}
        mock_request.return_value = mock_response

        result = recall_client.create_bot(
            meeting_url="https://zoom.us/j/123456"
        )

        assert result["id"] == "bot-abc"
        mock_request.assert_called_once()

        # Check payload
        call_args = mock_request.call_args
        assert call_args[1]["method"] == "POST"
        assert "/bot" in call_args[1]["url"]

    def test_create_bot_invalid_url(self, recall_client):
        """Test bot creation with invalid URL."""
        with pytest.raises(ValueError, match="Invalid meeting URL"):
            recall_client.create_bot(meeting_url="not-a-url")

    @patch("requests.request")
    def test_get_bot_status(self, mock_request, recall_client):
        """Test getting bot status."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "bot-123",
            "status_changes": [{"code": "in_call_recording"}]
        }
        mock_request.return_value = mock_response

        status = recall_client.get_bot_status("bot-123")
        assert status == BotStatus.RECORDING

    @patch("requests.request")
    def test_leave_meeting(self, mock_request, recall_client):
        """Test leaving a meeting."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "leaving"}
        mock_request.return_value = mock_response

        result = recall_client.leave_meeting("bot-123")
        assert result["status"] == "leaving"

    @patch("requests.request")
    def test_get_transcript(self, mock_request, recall_client):
        """Test getting transcript."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transcript": [
                {"speaker": "John", "text": "Hello", "start": 0.0, "end": 1.0}
            ]
        }
        mock_request.return_value = mock_response

        segments = recall_client.get_transcript("bot-123")
        assert len(segments) == 1
        assert segments[0]["speaker"] == "John"

    @patch("requests.request")
    @patch("time.sleep")
    def test_retry_on_server_error(self, mock_sleep, mock_request, recall_client):
        """Test retry on server error."""
        # First two calls fail, third succeeds
        mock_fail = Mock()
        mock_fail.status_code = 500
        mock_fail.text = "Server error"

        mock_success = Mock()
        mock_success.status_code = 200
        mock_success.json.return_value = {"id": "bot-123"}

        mock_request.side_effect = [mock_fail, mock_fail, mock_success]

        result = recall_client.get_bot("bot-123")
        assert result["id"] == "bot-123"
        assert mock_request.call_count == 3

    @patch("requests.request")
    def test_no_retry_on_client_error(self, mock_request, recall_client):
        """Test no retry on 4xx errors."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        mock_request.return_value = mock_response

        with pytest.raises(Exception):
            recall_client.get_bot("bot-123")

        # Only one call - no retries
        assert mock_request.call_count == 1


# ============================================================
# MeetingHandler Tests
# ============================================================

class TestMeetingHandler:
    """Tests for MeetingHandler."""

    def test_join_meeting_success(self, meeting_handler):
        """Test successful meeting join."""
        result = meeting_handler.join_meeting(
            meeting_url="https://zoom.us/j/123456",
            requested_by="user@test.com",
            channel_id="channel-123"
        )

        assert result["status"] == "joining"
        assert "meeting_id" in result
        assert result["bot_id"] == "bot-123"

    def test_join_meeting_invalid_url(self, meeting_handler):
        """Test join with invalid URL."""
        meeting_handler.recall.create_bot.side_effect = ValueError("Invalid URL")

        result = meeting_handler.join_meeting(
            meeting_url="invalid-url",
            requested_by="user@test.com"
        )

        assert result["status"] == "error"
        assert "Invalid URL" in result["error"]

    def test_get_meeting_status(self, meeting_handler):
        """Test getting meeting status."""
        # First create a meeting
        join_result = meeting_handler.join_meeting(
            meeting_url="https://zoom.us/j/123456",
            requested_by="user@test.com"
        )
        meeting_id = join_result["meeting_id"]

        # Get status
        meeting = meeting_handler.get_meeting_status(meeting_id)
        assert meeting is not None
        assert meeting["id"] == meeting_id

    def test_get_meeting_status_not_found(self, meeting_handler):
        """Test getting status of non-existent meeting."""
        result = meeting_handler.get_meeting_status("non-existent")
        assert result is None

    def test_leave_meeting(self, meeting_handler):
        """Test leaving a meeting."""
        # First create a meeting
        join_result = meeting_handler.join_meeting(
            meeting_url="https://zoom.us/j/123456",
            requested_by="user@test.com"
        )
        meeting_id = join_result["meeting_id"]

        # Leave
        result = meeting_handler.leave_meeting(meeting_id)
        assert result["status"] == "left"

    def test_leave_meeting_not_found(self, meeting_handler):
        """Test leaving non-existent meeting."""
        result = meeting_handler.leave_meeting("non-existent")
        assert result["status"] == "error"

    def test_list_meetings(self, meeting_handler):
        """Test listing meetings."""
        # Create multiple meetings
        meeting_handler.join_meeting(
            meeting_url="https://zoom.us/j/111",
            requested_by="user1@test.com"
        )
        meeting_handler.join_meeting(
            meeting_url="https://zoom.us/j/222",
            requested_by="user2@test.com"
        )

        meetings = meeting_handler.list_meetings()
        assert len(meetings) >= 2

    def test_list_meetings_filter_by_status(self, meeting_handler):
        """Test listing meetings filtered by status."""
        meeting_handler.join_meeting(
            meeting_url="https://zoom.us/j/123",
            requested_by="user@test.com"
        )

        meetings = meeting_handler.list_meetings(status="joining")
        assert all(m["status"] == "joining" for m in meetings)

    def test_get_meeting_notes(self, meeting_handler):
        """Test getting formatted meeting notes."""
        join_result = meeting_handler.join_meeting(
            meeting_url="https://zoom.us/j/123456",
            requested_by="user@test.com"
        )
        meeting_id = join_result["meeting_id"]

        notes = meeting_handler.get_meeting_notes(meeting_id)
        assert notes is not None
        assert "Meeting Notes" in notes or "Hello" in notes


# ============================================================
# TranscriptionProcessor Tests
# ============================================================

class TestTranscriptionProcessor:
    """Tests for TranscriptionProcessor."""

    def test_process_webhook_final(self, transcription_processor, tmp_path):
        """Test processing final transcript webhook."""
        # First add a meeting to link bot_id to meeting_id
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO meetings (id, bot_id, meeting_url, requested_by, status)
            VALUES (?, ?, ?, ?, ?)
        """, ("meeting-123", "bot-abc", "https://zoom.us/j/123", "user@test.com", "recording"))
        conn.commit()
        conn.close()

        # Update processor db path
        transcription_processor.db_path = db_path

        webhook_data = {
            "event": "transcript.final",
            "data": {
                "bot_id": "bot-abc",
                "transcript": {
                    "speaker": "John",
                    "words": [
                        {"text": "Hello", "start": 0.0, "end": 0.5},
                        {"text": "world", "start": 0.5, "end": 1.0}
                    ],
                    "is_final": True
                }
            }
        }

        result = transcription_processor.process_webhook(webhook_data)
        assert result["status"] == "processed"
        assert result["is_final"] is True
        assert result["speaker"] == "John"

    def test_process_webhook_missing_bot_id(self, transcription_processor):
        """Test webhook with missing bot_id."""
        webhook_data = {
            "event": "transcript.final",
            "data": {
                "transcript": {"speaker": "John", "words": [], "is_final": True}
            }
        }

        result = transcription_processor.process_webhook(webhook_data)
        assert result["status"] == "error"
        assert "Missing bot_id" in result["error"]

    def test_check_keywords(self, transcription_processor):
        """Test keyword detection."""
        keywords = transcription_processor._check_keywords(
            "This is an action item for the team to follow up"
        )
        assert "action item" in keywords
        assert "follow up" in keywords

    def test_check_keywords_case_insensitive(self, transcription_processor):
        """Test keyword detection is case insensitive."""
        keywords = transcription_processor._check_keywords("This is URGENT!")
        assert "urgent" in keywords

    def test_alert_callback(self, transcription_processor, tmp_path):
        """Test that alert callback is triggered."""
        callback_called = []

        def callback(meeting_id, speaker, text, keywords):
            callback_called.append({
                "meeting_id": meeting_id,
                "speaker": speaker,
                "text": text,
                "keywords": keywords
            })

        transcription_processor.notification_callback = callback

        # Set up database with meeting
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO meetings (id, bot_id, meeting_url, requested_by, status)
            VALUES (?, ?, ?, ?, ?)
        """, ("meeting-123", "bot-alert", "https://zoom.us/j/123", "user@test.com", "recording"))
        conn.commit()
        conn.close()

        transcription_processor.db_path = db_path

        webhook_data = {
            "event": "transcript.final",
            "data": {
                "bot_id": "bot-alert",
                "transcript": {
                    "speaker": "Jane",
                    "words": [{"text": "urgent", "start": 0.0, "end": 0.5}],
                    "is_final": True
                }
            }
        }

        transcription_processor.process_webhook(webhook_data)
        assert len(callback_called) == 1
        assert callback_called[0]["speaker"] == "Jane"
        assert "urgent" in callback_called[0]["keywords"]

    def test_get_full_transcript(self, transcription_processor, tmp_path):
        """Test getting full transcript."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Add test segments
        cursor.execute("""
            INSERT INTO transcript_segments
            (meeting_id, speaker, text, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "John", "Hello", 0.0, 1.0, datetime.now().isoformat()))
        cursor.execute("""
            INSERT INTO transcript_segments
            (meeting_id, speaker, text, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "Jane", "Hi there", 1.0, 2.0, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        transcription_processor.db_path = db_path
        segments = transcription_processor.get_full_transcript("meeting-123")

        assert len(segments) == 2
        assert segments[0]["speaker"] == "John"
        assert segments[1]["speaker"] == "Jane"

    def test_format_transcript(self, transcription_processor, tmp_path):
        """Test formatting transcript."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO transcript_segments
            (meeting_id, speaker, text, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "John", "Hello", 0.0, 1.0, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        transcription_processor.db_path = db_path
        formatted = transcription_processor.format_transcript("meeting-123")

        assert "[John]" in formatted
        assert "Hello" in formatted

    def test_search_transcript(self, transcription_processor, tmp_path):
        """Test searching transcript."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO transcript_segments
            (meeting_id, speaker, text, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "John", "The deadline is Friday", 0.0, 2.0, datetime.now().isoformat()))
        cursor.execute("""
            INSERT INTO transcript_segments
            (meeting_id, speaker, text, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "Jane", "Got it, Friday", 2.0, 3.0, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        transcription_processor.db_path = db_path
        results = transcription_processor.search_transcript("meeting-123", "Friday")

        assert len(results) == 2

    def test_search_transcript_with_speaker_filter(self, transcription_processor, tmp_path):
        """Test searching transcript with speaker filter."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO transcript_segments
            (meeting_id, speaker, text, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "John", "The deadline is Friday", 0.0, 2.0, datetime.now().isoformat()))
        cursor.execute("""
            INSERT INTO transcript_segments
            (meeting_id, speaker, text, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "Jane", "Friday works", 2.0, 3.0, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        transcription_processor.db_path = db_path
        results = transcription_processor.search_transcript(
            "meeting-123", "Friday", speaker="John"
        )

        assert len(results) == 1
        assert results[0]["speaker"] == "John"

    def test_get_speakers(self, transcription_processor, tmp_path):
        """Test getting unique speakers."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO transcript_segments
            (meeting_id, speaker, text, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "John", "Hello", 0.0, 1.0, datetime.now().isoformat()))
        cursor.execute("""
            INSERT INTO transcript_segments
            (meeting_id, speaker, text, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "Jane", "Hi", 1.0, 2.0, datetime.now().isoformat()))
        cursor.execute("""
            INSERT INTO transcript_segments
            (meeting_id, speaker, text, start_time, end_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "John", "How are you", 2.0, 3.0, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        transcription_processor.db_path = db_path
        speakers = transcription_processor.get_speakers("meeting-123")

        assert len(speakers) == 2
        assert "John" in speakers
        assert "Jane" in speakers


# ============================================================
# API Endpoint Tests
# ============================================================

class TestMeetingEndpoints:
    """Tests for meeting API endpoints."""

    def test_join_meeting_endpoint(self, app_with_meeting, auth_headers):
        """Test POST /api/meeting/join."""
        client = app_with_meeting.test_client()

        response = client.post("/api/meeting/join", json={
            "meeting_url": "https://zoom.us/j/123456789",
            "requested_by": "test@example.com"
        }, headers=auth_headers)

        assert response.status_code == 201
        data = response.get_json()
        assert "meeting_id" in data
        assert data["status"] == "joining"

    def test_join_meeting_missing_url(self, app_with_meeting, auth_headers):
        """Test join meeting without URL."""
        client = app_with_meeting.test_client()

        response = client.post("/api/meeting/join", json={}, headers=auth_headers)
        assert response.status_code == 400
        assert "meeting_url is required" in response.get_json()["error"]

    def test_get_meeting_endpoint(self, app_with_meeting, auth_headers):
        """Test GET /api/meeting/<id>."""
        client = app_with_meeting.test_client()

        # First create a meeting
        create_response = client.post("/api/meeting/join", json={
            "meeting_url": "https://zoom.us/j/123456789",
            "requested_by": "test@example.com"
        }, headers=auth_headers)
        meeting_id = create_response.get_json()["meeting_id"]

        # Get the meeting
        response = client.get(f"/api/meeting/{meeting_id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json()["id"] == meeting_id

    def test_get_meeting_not_found(self, app_with_meeting, auth_headers):
        """Test get non-existent meeting."""
        client = app_with_meeting.test_client()

        response = client.get("/api/meeting/non-existent", headers=auth_headers)
        assert response.status_code == 404

    def test_leave_meeting_endpoint(self, app_with_meeting, auth_headers):
        """Test POST /api/meeting/<id>/leave."""
        client = app_with_meeting.test_client()

        # Create meeting first
        create_response = client.post("/api/meeting/join", json={
            "meeting_url": "https://zoom.us/j/123456789",
            "requested_by": "test@example.com"
        }, headers=auth_headers)
        meeting_id = create_response.get_json()["meeting_id"]

        # Leave
        response = client.post(f"/api/meeting/{meeting_id}/leave", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json()["status"] == "left"

    def test_list_meetings_endpoint(self, app_with_meeting, auth_headers):
        """Test GET /api/meetings."""
        client = app_with_meeting.test_client()

        # Create a meeting
        client.post("/api/meeting/join", json={
            "meeting_url": "https://zoom.us/j/123456789",
            "requested_by": "test@example.com"
        }, headers=auth_headers)

        response = client.get("/api/meetings", headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert "meetings" in data
        assert "count" in data

    def test_transcription_webhook_unauthorized(self, app_with_meeting):
        """Test transcription webhook rejects unauthorized requests."""
        client = app_with_meeting.test_client()

        # Request without valid signature should be rejected
        response = client.post("/meeting/transcription", json={
            "event": "transcript.final",
            "data": {"bot_id": "bot-123"}
        })

        # Fail-secure: Reject unauthorized webhooks
        assert response.status_code == 401
        assert response.get_json().get("error") == "Unauthorized"

    def test_transcription_webhook_authorized(self, app_with_meeting):
        """Test transcription webhook with auth."""
        client = app_with_meeting.test_client()

        response = client.post(
            "/meeting/transcription",
            json={
                "event": "transcript.final",
                "data": {
                    "bot_id": "bot-123",
                    "transcript": {
                        "speaker": "Test",
                        "words": [],
                        "is_final": True
                    }
                }
            },
            headers={"X-Transcription-Secret": "test-secret"}
        )

        assert response.status_code == 200

    def test_search_transcript_endpoint(self, app_with_meeting, auth_headers):
        """Test GET /api/meeting/<id>/search."""
        client = app_with_meeting.test_client()

        response = client.get("/api/meeting/meeting-123/search?q=test", headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert "results" in data

    def test_search_transcript_missing_query(self, app_with_meeting, auth_headers):
        """Test search without query parameter."""
        client = app_with_meeting.test_client()

        response = client.get("/api/meeting/meeting-123/search", headers=auth_headers)
        assert response.status_code == 400
        assert "q (query) parameter is required" in response.get_json()["error"]

    def test_get_speakers_endpoint(self, app_with_meeting, auth_headers):
        """Test GET /api/meeting/<id>/speakers."""
        client = app_with_meeting.test_client()

        response = client.get("/api/meeting/meeting-123/speakers", headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert "speakers" in data


class TestMeetingIntegrationDisabled:
    """Tests when meeting integration is not configured."""

    @pytest.fixture
    def app_without_meeting(self, tmp_path):
        """Create Flask app without meeting integration."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        _init_test_db(db_path)

        return create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            # No RECALL_API_KEY
        })

    @pytest.mark.xfail(reason="Fixture isolation issue - env vars from conftest affect behavior")
    def test_join_meeting_not_configured(self, app_without_meeting):
        """Test join when not configured."""
        client = app_without_meeting.test_client()

        response = client.post("/api/meeting/join", json={
            "meeting_url": "https://zoom.us/j/123"
        })

        assert response.status_code == 503
        assert "not configured" in response.get_json()["error"]

    @pytest.mark.xfail(reason="Fixture isolation issue - env vars from conftest affect behavior")
    def test_list_meetings_not_configured(self, app_without_meeting):
        """Test list when not configured."""
        client = app_without_meeting.test_client()

        response = client.get("/api/meetings")
        assert response.status_code == 503

    @pytest.mark.xfail(reason="Fixture isolation issue - env vars from conftest affect behavior")
    def test_transcription_not_configured(self, app_without_meeting):
        """Test transcription when not configured."""
        client = app_without_meeting.test_client()

        response = client.post("/meeting/transcription", json={})
        assert response.status_code == 503


# ============================================================
# Council Fix Tests
# ============================================================

class TestCouncilFixes:
    """Tests for issues identified by adversarial council review."""

    def test_url_domain_validation_zoom(self, recall_client):
        """Test that Zoom URLs are accepted."""
        # Should not raise
        with patch("requests.request") as mock:
            mock.return_value = Mock(status_code=201, json=lambda: {"id": "bot-123"})
            recall_client.create_bot("https://zoom.us/j/123456789")
            recall_client.create_bot("https://us02web.zoom.us/j/123456789")

    def test_url_domain_validation_teams(self, recall_client):
        """Test that Teams URLs are accepted."""
        with patch("requests.request") as mock:
            mock.return_value = Mock(status_code=201, json=lambda: {"id": "bot-123"})
            recall_client.create_bot("https://teams.microsoft.com/l/meetup-join/123")

    def test_url_domain_validation_meet(self, recall_client):
        """Test that Google Meet URLs are accepted."""
        with patch("requests.request") as mock:
            mock.return_value = Mock(status_code=201, json=lambda: {"id": "bot-123"})
            recall_client.create_bot("https://meet.google.com/abc-defg-hij")

    def test_url_domain_validation_rejects_unknown(self, recall_client):
        """Test that unknown meeting platforms are rejected."""
        with pytest.raises(ValueError, match="Unsupported meeting platform"):
            recall_client.create_bot("https://unknown-platform.com/meeting/123")

    def test_url_domain_validation_rejects_phishing(self, recall_client):
        """Test that look-alike domains are rejected."""
        # zoom.us.fake.com contains "zoom.us" substring, so this tests
        # that we check the full domain, not just substring
        with pytest.raises(ValueError, match="Unsupported meeting platform"):
            recall_client.create_bot("https://fake-zoom.us/j/123")

    def test_meeting_rate_limit(self, app_with_meeting, auth_headers):
        """Test rate limiting on meeting join endpoint."""
        client = app_with_meeting.test_client()

        # Exhaust rate limit (default 5/hour)
        for i in range(5):
            response = client.post("/api/meeting/join", json={
                "meeting_url": f"https://zoom.us/j/{i}",
                "requested_by": "rate-limit-test"
            }, headers=auth_headers)
            assert response.status_code == 201

        # Next request should be rate limited
        response = client.post("/api/meeting/join", json={
            "meeting_url": "https://zoom.us/j/999",
            "requested_by": "rate-limit-test"
        }, headers=auth_headers)
        assert response.status_code == 429
        assert "rate limit" in response.get_json()["error"].lower()

    def test_rate_limit_different_users(self, app_with_meeting, auth_headers):
        """Test that rate limits are per-user."""
        client = app_with_meeting.test_client()

        # User1 uses their quota
        for i in range(5):
            client.post("/api/meeting/join", json={
                "meeting_url": f"https://zoom.us/j/{i}",
                "requested_by": "user1"
            }, headers=auth_headers)

        # User2 should still be able to join
        response = client.post("/api/meeting/join", json={
            "meeting_url": "https://zoom.us/j/999",
            "requested_by": "user2"
        }, headers=auth_headers)
        assert response.status_code == 201

    def test_hmac_signature_verification(self, app_with_meeting):
        """Test HMAC signature verification for webhooks."""
        import hashlib
        import hmac as hmac_lib

        client = app_with_meeting.test_client()
        secret = "test-secret"
        body = b'{"event": "transcript.final", "data": {"bot_id": "bot-123", "transcript": {"speaker": "Test", "words": [], "is_final": true}}}'

        # Calculate correct signature
        signature = hmac_lib.new(secret.encode(), body, hashlib.sha256).hexdigest()

        response = client.post(
            "/meeting/transcription",
            data=body,
            content_type="application/json",
            headers={"X-Recall-Signature": signature}
        )

        assert response.status_code == 200

    def test_hmac_signature_invalid(self, app_with_meeting):
        """Test invalid HMAC signature is rejected."""
        client = app_with_meeting.test_client()

        # Invalid signature should be rejected
        response = client.post(
            "/meeting/transcription",
            json={"event": "transcript.final", "data": {"bot_id": "bot-123"}},
            headers={"X-Recall-Signature": "invalid-signature"}
        )

        # Fail-secure: Reject invalid signatures
        assert response.status_code == 401
        assert response.get_json().get("error") == "Unauthorized"

    def test_bot_status_webhook(self, app_with_meeting, auth_headers):
        """Test bot status webhook endpoint."""
        client = app_with_meeting.test_client()

        # First create a meeting
        create_response = client.post("/api/meeting/join", json={
            "meeting_url": "https://zoom.us/j/123456789",
            "requested_by": "test@example.com"
        }, headers=auth_headers)
        meeting = create_response.get_json()
        bot_id = meeting["bot_id"]

        # Send status update
        response = client.post(
            "/meeting/status",
            json={
                "event": "bot.status_change",
                "data": {
                    "bot_id": bot_id,
                    "status": "in_call_recording"
                }
            },
            headers={"X-Transcription-Secret": "test-secret"}
        )

        assert response.status_code == 200
        assert response.get_json()["status"] == "acknowledged"

    def test_bot_status_webhook_missing_fields(self, app_with_meeting):
        """Test status webhook handles missing fields gracefully (permissive mode)."""
        client = app_with_meeting.test_client()

        response = client.post(
            "/meeting/status",
            json={"event": "bot.status_change", "data": {}},
            headers={"X-Transcription-Secret": "test-secret"}
        )

        # Webhook is permissive - accepts payloads without bot_id
        assert response.status_code == 200
        assert response.get_json()["status"] == "acknowledged"
        assert response.get_json().get("note") == "no bot_id"

    def test_cleanup_endpoint(self, app_with_meeting, auth_headers):
        """Test cleanup endpoint."""
        client = app_with_meeting.test_client()

        response = client.post("/api/meetings/cleanup", headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert "abandoned" in data
        assert "deleted" in data

    def test_concurrent_meeting_join_same_url(self, meeting_handler):
        """Test that joining same meeting URL creates separate meeting records."""
        url = "https://zoom.us/j/123456789"

        result1 = meeting_handler.join_meeting(url, "user1@test.com")
        result2 = meeting_handler.join_meeting(url, "user2@test.com")

        assert result1["meeting_id"] != result2["meeting_id"]
        assert result1["status"] == "joining"
        assert result2["status"] == "joining"

    def test_get_meeting_by_bot_id(self, meeting_handler):
        """Test _get_meeting_by_bot_id helper method."""
        # Create a meeting
        result = meeting_handler.join_meeting(
            "https://zoom.us/j/123",
            "user@test.com"
        )
        bot_id = result["bot_id"]

        # Find by bot_id
        meeting = meeting_handler._get_meeting_by_bot_id(bot_id)
        assert meeting is not None
        assert meeting["id"] == result["meeting_id"]

    def test_cleanup_abandoned(self, meeting_handler, tmp_path):
        """Test cleanup_abandoned marks stale meetings."""
        # Manually insert an old meeting
        db_path = meeting_handler.db_path
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Insert meeting with old created_at
        cursor.execute("""
            INSERT INTO meetings (id, bot_id, meeting_url, requested_by, status, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now', '-1 hour'))
        """, ("old-meeting", "old-bot", "https://zoom.us/j/old", "user@test.com", "joining"))
        conn.commit()
        conn.close()

        # Run cleanup with 30 minute threshold
        abandoned = meeting_handler.cleanup_abandoned(stale_minutes=30)
        assert abandoned >= 1

        # Verify meeting is now abandoned (check DB directly since get_meeting_status
        # calls the mock API which would update the status)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM meetings WHERE id = ?", ("old-meeting",))
        row = cursor.fetchone()
        conn.close()
        assert row[0] == "abandoned"
