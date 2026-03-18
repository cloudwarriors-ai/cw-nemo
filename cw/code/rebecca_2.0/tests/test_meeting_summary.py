"""
Tests for meeting summary generation.

Tests QABrain meeting summary methods and database transcript retrieval.
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.bot.llm_brain import QABrain


class TestMeetingSummaryGeneration:
    """Tests for QABrain meeting summary generation."""

    @pytest.fixture
    def mock_qa_brain(self):
        """Create a QABrain with mocked LLM calls."""
        with patch.object(QABrain, '__init__', lambda self, **kwargs: None):
            brain = QABrain()
            brain.api_key = "test-key"
            brain.model = "test-model"
            brain.repos = []
            brain.logger = MagicMock()
            brain.config = MagicMock()
            brain.config.timeout_seconds = 30
            brain._circuit_breaker = MagicMock()
            brain._circuit_breaker.can_execute.return_value = True
            brain._session = MagicMock()
            brain._sensitive_patterns = []
            return brain

    def test_generate_meeting_summary_short_transcript(self, mock_qa_brain):
        """Test summary generation for short transcripts."""
        transcript = """
        Chad: Good morning everyone. Let's discuss the sprint priorities.
        Alice: I think we should focus on the authentication bug first.
        Chad: Agreed. Alice, can you take that on?
        Alice: Yes, I'll have a PR ready by Thursday.
        Bob: I'll review it when it's ready.
        Chad: Great. Any blockers?
        Bob: No blockers from my side.
        Chad: Perfect. Meeting adjourned.
        """

        # Mock the LLM call
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "**Key Decisions**\n- Focus on authentication bug\n\n**Action Items**\n- Alice: Submit PR by Thursday"}}],
            "usage": {"total_tokens": 100}
        }
        mock_qa_brain._session.post.return_value = mock_response

        summary = mock_qa_brain.generate_meeting_summary(
            transcript=transcript,
            meeting_name="Sprint Planning",
            meeting_date="January 15, 2024",
            participants=["Chad", "Alice", "Bob"]
        )

        assert "Key Decisions" in summary or "Authentication" in summary.lower()
        mock_qa_brain._session.post.assert_called()

    def test_generate_meeting_summary_circuit_breaker_open(self, mock_qa_brain):
        """Test fallback when circuit breaker is open."""
        mock_qa_brain._circuit_breaker.can_execute.return_value = False

        summary = mock_qa_brain.generate_meeting_summary(
            transcript="Test transcript",
            meeting_name="Test Meeting"
        )

        assert "unable" in summary.lower() or "unavailable" in summary.lower()

    def test_generate_meeting_summary_error_handling(self, mock_qa_brain):
        """Test error handling during summary generation."""
        mock_qa_brain._session.post.side_effect = Exception("API error")

        summary = mock_qa_brain.generate_meeting_summary(
            transcript="Test transcript",
            meeting_name="Test Meeting"
        )

        assert "unable" in summary.lower() or "error" in summary.lower()

    def test_generate_meeting_summary_default_values(self, mock_qa_brain):
        """Test summary generation with default values."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Meeting summary content"}}],
            "usage": {"total_tokens": 50}
        }
        mock_qa_brain._session.post.return_value = mock_response

        summary = mock_qa_brain.generate_meeting_summary(
            transcript="Simple test transcript"
        )

        assert summary == "Meeting summary content"
        # Verify API was called with default meeting name
        call_args = mock_qa_brain._session.post.call_args
        assert "DevOps Meeting" in str(call_args)


class TestLongTranscriptChunking:
    """Tests for long transcript chunking logic."""

    @pytest.fixture
    def mock_qa_brain(self):
        """Create a QABrain with mocked LLM calls."""
        with patch.object(QABrain, '__init__', lambda self, **kwargs: None):
            brain = QABrain()
            brain.api_key = "test-key"
            brain.model = "test-model"
            brain.repos = []
            brain.logger = MagicMock()
            brain.config = MagicMock()
            brain.config.timeout_seconds = 30
            brain._circuit_breaker = MagicMock()
            brain._circuit_breaker.can_execute.return_value = True
            brain._session = MagicMock()
            brain._sensitive_patterns = []
            return brain

    def test_long_transcript_uses_chunking(self, mock_qa_brain):
        """Test that long transcripts trigger chunking."""
        # Create a long transcript (>12000 chars for 3000 token threshold)
        long_transcript = "Speaker: " + "This is a test sentence. " * 1000

        # Mock responses for chunk processing
        chunk_response = MagicMock()
        chunk_response.status_code = 200
        chunk_response.json.return_value = {
            "choices": [{"message": {"content": '{"decisions": ["Test decision"], "action_items": [], "discussion_points": ["Test point"], "blockers": [], "notable_quotes": []}'}}],
            "usage": {"total_tokens": 50}
        }

        final_response = MagicMock()
        final_response.status_code = 200
        final_response.json.return_value = {
            "choices": [{"message": {"content": "Combined meeting summary"}}],
            "usage": {"total_tokens": 100}
        }

        # Alternate between chunk and final responses
        mock_qa_brain._session.post.side_effect = [chunk_response, chunk_response, final_response]

        summary = mock_qa_brain.generate_meeting_summary(
            transcript=long_transcript,
            meeting_name="Long Meeting"
        )

        # Should have called LLM multiple times (chunks + final)
        assert mock_qa_brain._session.post.call_count >= 2


class TestGetMeetingTranscript:
    """Tests for database transcript retrieval."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database with meeting data."""
        db_path = str(tmp_path / "test.db")

        from src.bot.database import init_db

        init_db(db_path)

        # Add a meeting with transcript
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO meetings (id, bot_id, meeting_url, status, created_at, ended_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("meeting-123", "bot-1", "https://zoom.us/j/123", "ended",
              "2024-01-15T10:00:00", "2024-01-15T11:00:00"))

        # Add transcript segments
        cursor.execute("""
            INSERT INTO transcript_segments (meeting_id, speaker, text, start_time, end_time)
            VALUES (?, ?, ?, ?, ?)
        """, ("meeting-123", "Chad", "Hello everyone", 0.0, 2.0))

        cursor.execute("""
            INSERT INTO transcript_segments (meeting_id, speaker, text, start_time, end_time)
            VALUES (?, ?, ?, ?, ?)
        """, ("meeting-123", "Alice", "Hi Chad", 2.5, 4.0))

        conn.commit()
        conn.close()

        return db_path

    def test_get_meeting_transcript_success(self, temp_db):
        """Test successful transcript retrieval."""
        from src.bot.database import get_meeting_transcript

        result = get_meeting_transcript(temp_db, "meeting-123")

        assert result is not None
        assert result["meeting_id"] == "meeting-123"
        assert "Chad: Hello everyone" in result["transcript"]
        assert "Alice: Hi Chad" in result["transcript"]
        assert "Chad" in result["participants"]
        assert "Alice" in result["participants"]
        assert result["duration"] is not None

    def test_get_meeting_transcript_not_found(self, temp_db):
        """Test transcript retrieval for non-existent meeting."""
        from src.bot.database import get_meeting_transcript

        result = get_meeting_transcript(temp_db, "nonexistent-meeting")

        assert result is None

    def test_get_meeting_transcript_no_segments(self, tmp_path):
        """Test transcript retrieval when meeting has no segments."""
        db_path = str(tmp_path / "empty.db")

        from src.bot.database import init_db

        init_db(db_path)

        # Add meeting without transcript
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO meetings (id, bot_id, meeting_url, status, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, ("meeting-empty", "bot-1", "https://zoom.us/j/empty", "active", "2024-01-15T10:00:00"))
        conn.commit()
        conn.close()

        from src.bot.database import get_meeting_transcript
        result = get_meeting_transcript(db_path, "meeting-empty")

        assert result is not None
        assert result["transcript"] is None
        assert result["participants"] == []
