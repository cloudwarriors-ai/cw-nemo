"""
Input validation models using Pydantic.

Provides type-safe validation for API request bodies and parameters.
Returns 400 Bad Request with detailed validation errors for invalid input.

Usage:
    from .validation import validate_request, MeetingJoinRequest

    @meetings_bp.route("/api/meeting/join", methods=["POST"])
    def join_meeting():
        result = validate_request(MeetingJoinRequest)
        if result.is_err():
            return jsonify(result.error.to_dict()), 400

        data = result.unwrap()  # Type-safe MeetingJoinRequest
        meeting_url = data.meeting_url
        ...
"""
from typing import Optional, Type, TypeVar, List
from urllib.parse import urlparse
import re

from pydantic import BaseModel, Field, field_validator, model_validator
from flask import request

from .result import Result, Ok, Err, AppError, ErrorCode


T = TypeVar("T", bound=BaseModel)


# =============================================================================
# Validation Helper
# =============================================================================

def validate_request(model: Type[T]) -> Result[T, AppError]:
    """
    Validate the current Flask request JSON body against a Pydantic model.

    Args:
        model: Pydantic model class to validate against

    Returns:
        Ok(validated_data) if valid, Err(AppError) if validation fails

    Usage:
        @app.route("/api/meeting/join", methods=["POST"])
        def join_meeting():
            result = validate_request(MeetingJoinRequest)
            if result.is_err():
                return jsonify(result.error.to_dict()), 400

            data = result.unwrap()
            # data is now a type-safe MeetingJoinRequest instance
    """
    try:
        json_data = request.get_json(silent=True) or {}
        validated = model.model_validate(json_data)
        return Ok(validated)
    except Exception as e:
        # Extract validation errors from Pydantic
        error_details = {}
        if hasattr(e, "errors"):
            errors = e.errors()
            error_details = {
                "validation_errors": [
                    {
                        "field": ".".join(str(x) for x in err.get("loc", [])),
                        "message": err.get("msg", "Invalid value"),
                        "type": err.get("type", "unknown")
                    }
                    for err in errors
                ]
            }

        return Err(AppError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Request validation failed",
            details=error_details or {"error": str(e)}
        ))


def validate_query_params(model: Type[T]) -> Result[T, AppError]:
    """
    Validate the current Flask request query parameters against a Pydantic model.

    Args:
        model: Pydantic model class to validate against

    Returns:
        Ok(validated_data) if valid, Err(AppError) if validation fails
    """
    try:
        # Convert query params to dict
        params = dict(request.args)
        validated = model.model_validate(params)
        return Ok(validated)
    except Exception as e:
        error_details = {}
        if hasattr(e, "errors"):
            errors = e.errors()
            error_details = {
                "validation_errors": [
                    {
                        "field": ".".join(str(x) for x in err.get("loc", [])),
                        "message": err.get("msg", "Invalid value"),
                        "type": err.get("type", "unknown")
                    }
                    for err in errors
                ]
            }

        return Err(AppError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Query parameter validation failed",
            details=error_details or {"error": str(e)}
        ))


# =============================================================================
# Meeting API Models
# =============================================================================

class MeetingJoinRequest(BaseModel):
    """Validation model for /api/meeting/join endpoint."""

    meeting_url: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="URL of the meeting to join"
    )
    bot_name: Optional[str] = Field(
        None,
        max_length=50,
        description="Custom name for the bot in the meeting"
    )
    user_id: Optional[str] = Field(
        None,
        max_length=100,
        description="User ID for rate limiting"
    )
    enable_voice: Optional[bool] = Field(
        None,
        description="Enable voice responses via Output Media"
    )

    @field_validator("meeting_url")
    @classmethod
    def validate_meeting_url(cls, v: str) -> str:
        """Validate meeting URL is from a known provider."""
        valid_domains = [
            "zoom.us", "zoom.com",
            "us02web.zoom.us", "us04web.zoom.us", "us05web.zoom.us", "us06web.zoom.us",
            "teams.microsoft.com", "teams.live.com",
            "meet.google.com",
        ]
        try:
            parsed = urlparse(v)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("Invalid URL format")

            domain = parsed.netloc.lower()
            if not any(d in domain for d in valid_domains):
                raise ValueError(
                    f"Unsupported meeting platform. "
                    f"Supported: Zoom, Microsoft Teams, Google Meet"
                )
        except ValueError:
            raise
        except Exception:
            raise ValueError("Invalid meeting URL")

        return v


class MeetingJoinWithAvatarRequest(MeetingJoinRequest):
    """Validation model for /api/meeting/join-with-avatar endpoint."""

    avatar_mode: Optional[str] = Field(
        "websocket",
        description="Avatar rendering mode (websocket, static)"
    )

    @field_validator("avatar_mode")
    @classmethod
    def validate_avatar_mode(cls, v: str) -> str:
        """Validate avatar mode is supported."""
        valid_modes = ["websocket", "static"]
        if v and v not in valid_modes:
            raise ValueError(f"Invalid avatar mode. Supported: {', '.join(valid_modes)}")
        return v


class MeetingStatusRequest(BaseModel):
    """Validation model for meeting status endpoints."""

    meeting_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="ID of the meeting"
    )


class MeetingLeaveRequest(BaseModel):
    """Validation model for /api/meeting/leave endpoint."""

    meeting_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="ID of the meeting to leave"
    )
    reason: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional reason for leaving"
    )


# =============================================================================
# Zoom Webhook Models
# =============================================================================

class ZoomWebhookPayload(BaseModel):
    """Validation model for Zoom webhook payload."""

    event: Optional[str] = Field(None, description="Webhook event type")
    payload: Optional[dict] = Field(default_factory=dict, description="Event payload")
    token: Optional[str] = Field(None, description="Verification token")

    @model_validator(mode="after")
    def check_event_or_token(self):
        """Require either event or token for valid webhook."""
        if not self.event and not self.token:
            if not self.payload:
                raise ValueError("Webhook must have event, token, or payload")
        return self


class ZoomMessagePayload(BaseModel):
    """Validation model for Zoom message webhook payload."""

    messageId: Optional[str] = Field(None, alias="msgId")
    text: Optional[str] = Field(None, max_length=4000)
    cmd: Optional[str] = Field(None, max_length=4000)
    userId: Optional[str] = Field(None, max_length=100)
    userName: Optional[str] = Field(None, max_length=100)
    toJid: Optional[str] = Field(None, max_length=200)
    userJid: Optional[str] = Field(None, max_length=200)
    accountId: Optional[str] = Field(None, max_length=100)

    class Config:
        populate_by_name = True


# =============================================================================
# Query API Models
# =============================================================================

class QueryRequest(BaseModel):
    """Validation model for /api/query endpoint."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Query text to process"
    )
    user_id: Optional[str] = Field(
        None,
        max_length=100,
        description="User identifier for logging"
    )
    context: Optional[dict] = Field(
        None,
        description="Additional context for the query"
    )


class ZoomSendRequest(BaseModel):
    """Validation model for /api/zoom/send endpoint."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Message to send"
    )
    to_jid: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Target JID to send to"
    )
    account_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Zoom account ID"
    )
    user_jid: Optional[str] = Field(
        None,
        max_length=200,
        description="User JID for DM"
    )


# =============================================================================
# Intern Management Models
# =============================================================================

class InternCreateRequest(BaseModel):
    """Validation model for creating an intern."""

    github_username: str = Field(
        ...,
        min_length=1,
        max_length=39,  # GitHub username limit
        pattern=r'^[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$',
        description="GitHub username"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Intern's full name"
    )
    email: Optional[str] = Field(
        None,
        max_length=254,  # Email max length per RFC
        description="Intern's email address"
    )
    start_date: Optional[str] = Field(
        None,
        pattern=r'^\d{4}-\d{2}-\d{2}$',
        description="Start date in YYYY-MM-DD format"
    )
    end_date: Optional[str] = Field(
        None,
        pattern=r'^\d{4}-\d{2}-\d{2}$',
        description="End date in YYYY-MM-DD format"
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Basic email validation."""
        if v and "@" not in v:
            raise ValueError("Invalid email format")
        return v

    @model_validator(mode="after")
    def check_dates(self):
        """Validate end_date is after start_date if both provided."""
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValueError("End date must be after start date")
        return self


class InternUpdateRequest(BaseModel):
    """Validation model for updating an intern."""

    name: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=254)
    status: Optional[str] = Field(None)
    end_date: Optional[str] = Field(None, pattern=r'^\d{4}-\d{2}-\d{2}$')

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate intern status."""
        valid_statuses = ["active", "inactive", "completed", "offboarded"]
        if v and v.lower() not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        return v.lower() if v else v


# =============================================================================
# Workflow Models
# =============================================================================

class WorkflowTriggerRequest(BaseModel):
    """Validation model for triggering workflows."""

    workflow_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Type of workflow to trigger"
    )
    payload: Optional[dict] = Field(
        default_factory=dict,
        description="Workflow payload data"
    )
    context: Optional[dict] = Field(
        default_factory=dict,
        description="Workflow context"
    )

    @field_validator("workflow_type")
    @classmethod
    def validate_workflow_type(cls, v: str) -> str:
        """Validate workflow type is recognized."""
        valid_types = [
            "onboarding", "offboarding", "weekly_report",
            "daily_standup", "report_upload"
        ]
        if v.lower() not in valid_types:
            raise ValueError(f"Unknown workflow type. Valid types: {', '.join(valid_types)}")
        return v.lower()


# =============================================================================
# Voice/Avatar Models
# =============================================================================

class VoiceProcessRequest(BaseModel):
    """Validation model for voice processing."""

    audio_data: Optional[str] = Field(
        None,
        description="Base64 encoded audio data"
    )
    text: Optional[str] = Field(
        None,
        max_length=2000,
        description="Text to synthesize"
    )
    format: Optional[str] = Field(
        "wav",
        description="Audio format"
    )

    @model_validator(mode="after")
    def check_input(self):
        """Require either audio_data or text."""
        if not self.audio_data and not self.text:
            raise ValueError("Either audio_data or text must be provided")
        return self


class AvatarSessionRequest(BaseModel):
    """Validation model for avatar session creation."""

    session_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Optional session ID"
    )
    face_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Avatar face ID"
    )
    voice_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Voice ID for TTS"
    )
