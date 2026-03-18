"""
Recall.ai API client for meeting bot management.

Handles creating bots, joining meetings, and managing transcription.
Protected by circuit breaker for resilience against Recall.ai outages.
"""
import json
import logging
import time
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

import requests

from ..bot.circuit_breaker import get_circuit_breaker, CircuitOpenError


class BotStatus(Enum):
    """Status of a Recall.ai meeting bot."""
    READY = "ready"
    JOINING = "joining"
    IN_WAITING_ROOM = "in_waiting_room"
    IN_CALL = "in_call"
    RECORDING = "recording"
    DONE = "done"
    ERROR = "error"
    FATAL = "fatal"


class RecallClient:
    """
    Client for Recall.ai API to manage meeting bots.

    Recall.ai handles the complexity of joining Zoom meetings,
    capturing audio/video, and providing real-time transcription.
    """

    # US West region - Regions: us-east-1, us-west-2, eu-central-1, ap-northeast-1
    BASE_URL = "https://us-west-2.recall.ai/api/v1"

    # Allowed meeting platform domains
    ALLOWED_DOMAINS = [
        "zoom.us",
        "us02web.zoom.us",
        "us04web.zoom.us",
        "us05web.zoom.us",
        "us06web.zoom.us",
        "teams.microsoft.com",
        "meet.google.com",
    ]

    def __init__(
        self,
        api_key: str,
        bot_name: str = "QA Bot",
        bot_image_url: str = None,
        transcription_webhook_url: str = None,
        transcription_webhook_secret: str = None,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        logger: logging.Logger = None
    ):
        """
        Initialize the Recall.ai client.

        Args:
            api_key: Recall.ai API key
            bot_name: Default name for the meeting bot
            bot_image_url: URL to bot avatar image (256x256 or 512x512)
            transcription_webhook_url: URL to receive real-time transcription
            transcription_webhook_secret: Secret for webhook signature verification
            timeout_seconds: Request timeout
            max_retries: Max retry attempts for transient failures
            logger: Logger instance
        """
        self.api_key = api_key
        self.bot_name = bot_name
        self.bot_image_url = bot_image_url
        self.transcription_webhook_url = transcription_webhook_url
        self.transcription_webhook_secret = transcription_webhook_secret
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self.logger = logger or logging.getLogger("qa_agent")

        # Circuit breaker for Recall.ai API resilience
        self._circuit_breaker = get_circuit_breaker(
            name="recall",
            failure_threshold=5,
            recovery_timeout=60,
            logger=self.logger,
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        data: dict = None,
        retry_on_error: bool = True
    ) -> dict:
        """
        Make an authenticated request to Recall.ai API.

        Protected by circuit breaker to prevent cascading failures.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint (e.g., "/bot")
            data: Request body for POST/PUT
            retry_on_error: Whether to retry on transient failures

        Returns:
            Response JSON

        Raises:
            CircuitOpenError: If Recall.ai circuit breaker is open
            requests.RequestException: On API errors after retries
        """
        # Check circuit breaker before making API call
        if not self._circuit_breaker.can_execute():
            raise CircuitOpenError("Recall.ai API circuit breaker is open. Service unavailable.")

        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error = None
        attempts = self.max_retries if retry_on_error else 1

        for attempt in range(attempts):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    timeout=self.timeout
                )

                # Success
                if response.status_code in (200, 201, 202, 204):
                    self._circuit_breaker.record_success()
                    if response.status_code == 204:
                        return {}
                    return response.json()

                # Client error - don't retry, but record failure for 5xx-like errors
                if 400 <= response.status_code < 500:
                    error_msg = f"API error {response.status_code}: {response.text[:500]}"
                    self.logger.error(error_msg)
                    # 4xx errors are typically client issues, not service failures
                    # Don't record as circuit breaker failure
                    raise requests.HTTPError(error_msg)

                # Server error - retry
                last_error = f"API error {response.status_code}: {response.text[:200]}"
                self.logger.warning(f"Recall.ai server error (attempt {attempt + 1}): {last_error}")

            except (requests.Timeout, requests.ConnectionError) as e:
                last_error = str(e)
                self.logger.warning(f"Recall.ai connection error (attempt {attempt + 1}): {last_error}")

            # Exponential backoff
            if attempt < attempts - 1:
                time.sleep((2 ** attempt) * 0.5)

        # All retries exhausted - record as circuit breaker failure
        self._circuit_breaker.record_failure()
        raise requests.RequestException(f"Failed after {attempts} attempts: {last_error}")

    def create_bot(
        self,
        meeting_url: str,
        bot_name: str = None,
        bot_image_url: str = None,
        transcription_provider: str = "deepgram",
        automatic_leave: bool = True,
        recording_mode: str = "speaker_view",
        output_media_url: str = None,
        variant: str = None
    ) -> dict:
        """
        Create a bot to join a meeting.

        Args:
            meeting_url: Zoom/Teams/Meet meeting URL
            bot_name: Override default bot name
            bot_image_url: Override default bot avatar
            transcription_provider: "deepgram", "assembly_ai", "aws"
            automatic_leave: Leave when meeting ends
            recording_mode: "speaker_view", "gallery_view", "audio_only"
            output_media_url: URL of webpage to render as bot's camera (Output Media)
            variant: Bot variant ("web", "web_gpu", "native") - use web_gpu for avatar

        Returns:
            Bot creation response with bot ID
        """
        # Validate meeting URL
        parsed = urlparse(meeting_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid meeting URL: {meeting_url}")

        # Validate domain is an allowed meeting platform
        # Check that domain ends with (or exactly matches) an allowed domain
        # This prevents attacks like "zoom.us.evil.com" or "fake-zoom.us"
        domain = parsed.netloc.lower()
        is_allowed = False
        for allowed in self.ALLOWED_DOMAINS:
            if domain == allowed or domain.endswith("." + allowed):
                is_allowed = True
                break
        if not is_allowed:
            raise ValueError(
                f"Unsupported meeting platform: {parsed.netloc}. "
                f"Supported platforms: Zoom, Microsoft Teams, Google Meet"
            )

        # Build payload with all features (updated for new API schema)
        payload = {
            "meeting_url": meeting_url,
            "bot_name": bot_name or self.bot_name,
        }

        # Add automatic leave settings if enabled
        if automatic_leave:
            payload["automatic_leave"] = {
                "waiting_room_timeout": 300,  # 5 min in waiting room
                "noone_joined_timeout": 300,  # 5 min if no one joins
                "everyone_left_timeout": 60,  # 1 min after everyone leaves
            }

        # Recording config with transcription (new API structure)
        recording_config = {}

        # Add transcription if webhook configured
        if self.transcription_webhook_url:
            recording_config["transcript"] = {
                "provider": {
                    "meeting_captions": {}  # Use Zoom's native captions
                }
            }
            # Realtime endpoints at recording_config level
            endpoint_config = {
                "type": "webhook",
                "url": self.transcription_webhook_url,
                "events": ["transcript.data"]
            }
            # Add secret for webhook signature verification
            if self.transcription_webhook_secret:
                endpoint_config["config"] = {
                    "secret": self.transcription_webhook_secret
                }
            recording_config["realtime_endpoints"] = [endpoint_config]

        if recording_config:
            payload["recording_config"] = recording_config

        # Add Output Media configuration for avatar/voice output
        if output_media_url:
            payload["output_media"] = {
                "camera": {
                    "kind": "webpage",
                    "config": {
                        "url": output_media_url
                    }
                }
            }
            self.logger.info(f"Output Media configured: {output_media_url}")

        # Add bot variant (web_gpu recommended for avatar rendering)
        if variant:
            payload["variant"] = {"zoom": variant}

        self.logger.info(f"Creating bot for meeting: {meeting_url}")
        response = self._request("POST", "/bot", payload)
        self.logger.info(f"Bot created: {response.get('id')}")

        return response

    def get_bot(self, bot_id: str) -> dict:
        """
        Get bot details and current status.

        Args:
            bot_id: Bot ID from create_bot response

        Returns:
            Bot details including status
        """
        return self._request("GET", f"/bot/{bot_id}")

    def get_bot_status(self, bot_id: str) -> BotStatus:
        """
        Get the current status of a bot.

        Args:
            bot_id: Bot ID

        Returns:
            BotStatus enum value
        """
        bot = self.get_bot(bot_id)
        status_code = bot.get("status_changes", [{}])[-1].get("code", "")

        status_map = {
            "ready": BotStatus.READY,
            "joining_call": BotStatus.JOINING,
            "in_waiting_room": BotStatus.IN_WAITING_ROOM,
            "in_call_not_recording": BotStatus.IN_CALL,
            "in_call_recording": BotStatus.RECORDING,
            "call_ended": BotStatus.DONE,
            "done": BotStatus.DONE,
            "fatal": BotStatus.FATAL,
        }

        return status_map.get(status_code, BotStatus.ERROR)

    def leave_meeting(self, bot_id: str) -> dict:
        """
        Make the bot leave the meeting.

        Args:
            bot_id: Bot ID

        Returns:
            Response confirming leave
        """
        self.logger.info(f"Bot {bot_id} leaving meeting")
        return self._request("POST", f"/bot/{bot_id}/leave_call")

    def delete_bot(self, bot_id: str) -> None:
        """
        Delete a bot and its data.

        Args:
            bot_id: Bot ID
        """
        self.logger.info(f"Deleting bot {bot_id}")
        self._request("DELETE", f"/bot/{bot_id}")

    def get_transcript(self, bot_id: str) -> list[dict]:
        """
        Get the full transcript for a completed meeting.

        Args:
            bot_id: Bot ID

        Returns:
            List of transcript segments with speaker, text, timestamps
        """
        response = self._request("GET", f"/bot/{bot_id}/transcript")
        return response.get("transcript", [])

    def get_recording_url(self, bot_id: str) -> Optional[str]:
        """
        Get the recording URL for a completed meeting.

        Args:
            bot_id: Bot ID

        Returns:
            URL to download recording, or None if not available
        """
        bot = self.get_bot(bot_id)
        return bot.get("video_url")

    def list_bots(
        self,
        status: str = None,
        limit: int = 20,
        cursor: str = None
    ) -> dict:
        """
        List all bots with optional filtering.

        Args:
            status: Filter by status
            limit: Max results per page
            cursor: Pagination cursor

        Returns:
            Dict with "results" list and optional "next" cursor
        """
        endpoint = f"/bot?limit={limit}"
        if status:
            endpoint += f"&status={status}"
        if cursor:
            endpoint += f"&cursor={cursor}"

        return self._request("GET", endpoint)

    def send_chat_message(self, bot_id: str, message: str) -> dict:
        """
        Send a chat message in the meeting.

        Args:
            bot_id: Bot ID
            message: Message text to send

        Returns:
            Response confirming message sent
        """
        self.logger.info(f"Bot {bot_id} sending chat: {message[:50]}...")
        return self._request("POST", f"/bot/{bot_id}/send_chat_message", {
            "message": message
        })

    def wait_for_status(
        self,
        bot_id: str,
        target_status: BotStatus,
        timeout_seconds: int = 120,
        poll_interval: float = 2.0
    ) -> bool:
        """
        Wait for bot to reach a specific status.

        Args:
            bot_id: Bot ID
            target_status: Status to wait for
            timeout_seconds: Max time to wait
            poll_interval: Seconds between status checks

        Returns:
            True if target status reached, False on timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            current_status = self.get_bot_status(bot_id)

            if current_status == target_status:
                return True

            if current_status in (BotStatus.ERROR, BotStatus.FATAL, BotStatus.DONE):
                self.logger.warning(f"Bot {bot_id} reached terminal status: {current_status}")
                return False

            time.sleep(poll_interval)

        self.logger.warning(f"Timeout waiting for bot {bot_id} to reach {target_status}")
        return False

    def get_circuit_status(self) -> dict:
        """Get circuit breaker status for health checks."""
        return self._circuit_breaker.get_status()
