"""
Tests for Pydantic input validation models.
"""
import pytest
from pydantic import ValidationError

from src.bot.validation import (
    MeetingJoinRequest,
    MeetingJoinWithAvatarRequest,
    MeetingLeaveRequest,
    QueryRequest,
    ZoomSendRequest,
    InternCreateRequest,
    InternUpdateRequest,
    WorkflowTriggerRequest,
    VoiceProcessRequest,
)


class TestMeetingJoinRequest:
    """Tests for MeetingJoinRequest validation."""

    def test_valid_zoom_url(self):
        """Test valid Zoom meeting URL passes validation."""
        data = MeetingJoinRequest(
            meeting_url="https://us02web.zoom.us/j/1234567890"
        )
        assert data.meeting_url == "https://us02web.zoom.us/j/1234567890"

    def test_valid_teams_url(self):
        """Test valid Teams meeting URL passes validation."""
        data = MeetingJoinRequest(
            meeting_url="https://teams.microsoft.com/l/meetup-join/19%3ameeting_123"
        )
        assert "teams.microsoft.com" in data.meeting_url

    def test_valid_google_meet_url(self):
        """Test valid Google Meet URL passes validation."""
        data = MeetingJoinRequest(
            meeting_url="https://meet.google.com/abc-defg-hij"
        )
        assert "meet.google.com" in data.meeting_url

    def test_invalid_domain_rejected(self):
        """Test unsupported meeting domain is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MeetingJoinRequest(
                meeting_url="https://example.com/meeting"
            )
        assert "Unsupported meeting platform" in str(exc_info.value)

    def test_invalid_url_format(self):
        """Test invalid URL format is rejected."""
        with pytest.raises(ValidationError):
            MeetingJoinRequest(
                meeting_url="not-a-url"
            )

    def test_empty_url_rejected(self):
        """Test empty URL is rejected."""
        with pytest.raises(ValidationError):
            MeetingJoinRequest(
                meeting_url=""
            )

    def test_url_too_long(self):
        """Test URL exceeding max length is rejected."""
        with pytest.raises(ValidationError):
            MeetingJoinRequest(
                meeting_url="https://zoom.us/" + "a" * 2000
            )

    def test_optional_fields(self):
        """Test optional fields work correctly."""
        data = MeetingJoinRequest(
            meeting_url="https://zoom.us/j/123",
            bot_name="Test Bot",
            user_id="user123",
            enable_voice=True
        )
        assert data.bot_name == "Test Bot"
        assert data.user_id == "user123"
        assert data.enable_voice is True

    def test_bot_name_max_length(self):
        """Test bot name max length is enforced."""
        with pytest.raises(ValidationError):
            MeetingJoinRequest(
                meeting_url="https://zoom.us/j/123",
                bot_name="a" * 51  # Exceeds 50 char limit
            )


class TestMeetingJoinWithAvatarRequest:
    """Tests for MeetingJoinWithAvatarRequest validation."""

    def test_valid_with_avatar_mode(self):
        """Test valid request with avatar mode."""
        data = MeetingJoinWithAvatarRequest(
            meeting_url="https://zoom.us/j/123",
            avatar_mode="websocket"
        )
        assert data.avatar_mode == "websocket"

    def test_invalid_avatar_mode(self):
        """Test invalid avatar mode is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MeetingJoinWithAvatarRequest(
                meeting_url="https://zoom.us/j/123",
                avatar_mode="invalid_mode"
            )
        assert "Invalid avatar mode" in str(exc_info.value)

    def test_default_avatar_mode(self):
        """Test default avatar mode is websocket."""
        data = MeetingJoinWithAvatarRequest(
            meeting_url="https://zoom.us/j/123"
        )
        assert data.avatar_mode == "websocket"


class TestQueryRequest:
    """Tests for QueryRequest validation."""

    def test_valid_query(self):
        """Test valid query passes validation."""
        data = QueryRequest(query="What are the high priority issues?")
        assert data.query == "What are the high priority issues?"

    def test_empty_query_rejected(self):
        """Test empty query is rejected."""
        with pytest.raises(ValidationError):
            QueryRequest(query="")

    def test_query_too_long(self):
        """Test query exceeding max length is rejected."""
        with pytest.raises(ValidationError):
            QueryRequest(query="x" * 2001)  # Exceeds 2000 char limit

    def test_optional_context(self):
        """Test optional context field."""
        data = QueryRequest(
            query="test",
            user_id="user123",
            context={"channel": "zoom"}
        )
        assert data.context == {"channel": "zoom"}


class TestZoomSendRequest:
    """Tests for ZoomSendRequest validation."""

    def test_valid_send_request(self):
        """Test valid send request passes validation."""
        data = ZoomSendRequest(
            message="Hello, world!",
            to_jid="channel@conference.zoom.us"
        )
        assert data.message == "Hello, world!"
        assert data.to_jid == "channel@conference.zoom.us"

    def test_empty_message_rejected(self):
        """Test empty message is rejected."""
        with pytest.raises(ValidationError):
            ZoomSendRequest(
                message="",
                to_jid="channel@zoom.us"
            )

    def test_missing_to_jid_rejected(self):
        """Test missing to_jid is rejected."""
        with pytest.raises(ValidationError):
            ZoomSendRequest(
                message="Hello"
            )

    def test_message_too_long(self):
        """Test message exceeding max length is rejected."""
        with pytest.raises(ValidationError):
            ZoomSendRequest(
                message="x" * 4001,  # Exceeds 4000 char limit
                to_jid="channel@zoom.us"
            )


class TestInternCreateRequest:
    """Tests for InternCreateRequest validation."""

    def test_valid_intern(self):
        """Test valid intern creation request."""
        data = InternCreateRequest(
            github_username="testuser",
            name="Test User",
            email="test@example.com",
            start_date="2024-01-15",
            end_date="2024-06-15"
        )
        assert data.github_username == "testuser"
        assert data.name == "Test User"

    def test_invalid_github_username(self):
        """Test invalid GitHub username pattern is rejected."""
        with pytest.raises(ValidationError):
            InternCreateRequest(
                github_username="-invalid",  # Can't start with hyphen
                name="Test"
            )

    def test_github_username_too_long(self):
        """Test GitHub username exceeding 39 chars is rejected."""
        with pytest.raises(ValidationError):
            InternCreateRequest(
                github_username="a" * 40,
                name="Test"
            )

    def test_invalid_email(self):
        """Test invalid email is rejected."""
        with pytest.raises(ValidationError):
            InternCreateRequest(
                github_username="testuser",
                name="Test",
                email="not-an-email"
            )

    def test_invalid_date_format(self):
        """Test invalid date format is rejected."""
        with pytest.raises(ValidationError):
            InternCreateRequest(
                github_username="testuser",
                name="Test",
                start_date="2024/01/15"  # Wrong format
            )

    def test_end_date_before_start_date(self):
        """Test end date before start date is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            InternCreateRequest(
                github_username="testuser",
                name="Test",
                start_date="2024-06-15",
                end_date="2024-01-15"  # Before start
            )
        assert "End date must be after start date" in str(exc_info.value)


class TestInternUpdateRequest:
    """Tests for InternUpdateRequest validation."""

    def test_valid_status_update(self):
        """Test valid status update."""
        data = InternUpdateRequest(status="active")
        assert data.status == "active"

    def test_invalid_status(self):
        """Test invalid status is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            InternUpdateRequest(status="invalid_status")
        assert "Invalid status" in str(exc_info.value)

    def test_status_case_insensitive(self):
        """Test status is normalized to lowercase."""
        data = InternUpdateRequest(status="ACTIVE")
        assert data.status == "active"


class TestWorkflowTriggerRequest:
    """Tests for WorkflowTriggerRequest validation."""

    def test_valid_workflow(self):
        """Test valid workflow trigger request."""
        data = WorkflowTriggerRequest(
            workflow_type="onboarding",
            payload={"user": "test"}
        )
        assert data.workflow_type == "onboarding"

    def test_invalid_workflow_type(self):
        """Test invalid workflow type is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowTriggerRequest(workflow_type="unknown_workflow")
        assert "Unknown workflow type" in str(exc_info.value)

    def test_workflow_type_case_insensitive(self):
        """Test workflow type is normalized to lowercase."""
        data = WorkflowTriggerRequest(workflow_type="ONBOARDING")
        assert data.workflow_type == "onboarding"


class TestVoiceProcessRequest:
    """Tests for VoiceProcessRequest validation."""

    def test_valid_with_text(self):
        """Test valid request with text."""
        data = VoiceProcessRequest(text="Hello, world!")
        assert data.text == "Hello, world!"

    def test_valid_with_audio(self):
        """Test valid request with audio data."""
        data = VoiceProcessRequest(audio_data="base64encodedaudio==")
        assert data.audio_data == "base64encodedaudio=="

    def test_missing_both_rejected(self):
        """Test request without text or audio is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            VoiceProcessRequest()
        assert "Either audio_data or text must be provided" in str(exc_info.value)

    def test_text_too_long(self):
        """Test text exceeding max length is rejected."""
        with pytest.raises(ValidationError):
            VoiceProcessRequest(text="x" * 2001)


class TestMeetingLeaveRequest:
    """Tests for MeetingLeaveRequest validation."""

    def test_valid_leave_request(self):
        """Test valid leave request."""
        data = MeetingLeaveRequest(
            meeting_id="meeting-123",
            reason="Meeting ended"
        )
        assert data.meeting_id == "meeting-123"
        assert data.reason == "Meeting ended"

    def test_empty_meeting_id_rejected(self):
        """Test empty meeting_id is rejected."""
        with pytest.raises(ValidationError):
            MeetingLeaveRequest(meeting_id="")

    def test_optional_reason(self):
        """Test reason is optional."""
        data = MeetingLeaveRequest(meeting_id="meeting-123")
        assert data.reason is None
