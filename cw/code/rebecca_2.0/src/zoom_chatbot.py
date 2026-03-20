"""
Zoom Chatbot API client for sending messages to Team Chat.

This uses the Zoom Chatbot API to send messages back to users
in response to webhook events.
Protected by circuit breaker for resilience against Zoom API outages.
"""
import base64
import logging
import time
from typing import Optional, Dict, Any

import requests

from .bot.circuit_breaker import get_circuit_breaker, CircuitOpenError


class ZoomChatbot:
    """
    Client for Zoom Chatbot API.

    Handles OAuth authentication and message sending for Team Chat bots.
    """

    # Zoom API endpoints
    TOKEN_URL = "https://zoom.us/oauth/token"
    CHATBOT_URL = "https://api.zoom.us/v2/im/chat/messages"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        bot_jid: str = None,
        account_id: str = None,
        s2s_client_id: str = None,
        s2s_client_secret: str = None,
        s2s_account_id: str = None,
        logger: logging.Logger = None
    ):
        """
        Initialize Zoom Chatbot client.

        Args:
            client_id: Zoom OAuth Client ID (for Chatbot API)
            client_secret: Zoom OAuth Client Secret (for Chatbot API)
            bot_jid: Bot JID (from Team Chat subscription)
            account_id: Zoom Account ID
            s2s_client_id: Server-to-Server OAuth Client ID (for admin APIs)
            s2s_client_secret: Server-to-Server OAuth Client Secret
            s2s_account_id: Server-to-Server Account ID
            logger: Logger instance
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.bot_jid = bot_jid
        self.account_id = account_id
        # S2S credentials for admin APIs (user info, etc.)
        self.s2s_client_id = s2s_client_id
        self.s2s_client_secret = s2s_client_secret
        self.s2s_account_id = s2s_account_id or account_id
        self.logger = logger or logging.getLogger("qa_agent")

        # Token cache
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0
        # Separate cache for Server-to-Server (admin) token
        self._admin_token: Optional[str] = None
        self._admin_token_expiry: float = 0

        # Circuit breaker for Zoom API resilience
        self._circuit_breaker = get_circuit_breaker(
            name="zoom",
            failure_threshold=5,
            recovery_timeout=60,
            logger=self.logger,
        )

    def _get_access_token(self) -> str:
        """
        Get OAuth access token using Client Credentials grant.

        Returns:
            Access token string

        Raises:
            CircuitOpenError: If Zoom API circuit breaker is open
            requests.RequestException: On API errors
        """
        # Return cached token if still valid
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        # Check circuit breaker before making API call
        if not self._circuit_breaker.can_execute():
            raise CircuitOpenError("Zoom API circuit breaker is open. Service unavailable.")

        # Request new token
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        try:
            # Use client_credentials grant type for Team Chat bots
            # See: https://developers.zoom.us/docs/team-chat/chatbot/extend/tokens-and-identifiers/
            response = requests.post(
                f"{self.TOKEN_URL}?grant_type=client_credentials",
                headers={
                    "Authorization": f"Basic {auth_header}",
                },
                timeout=10
            )

            # Log response details on failure
            if response.status_code != 200:
                self.logger.error(f"Token request failed: {response.status_code} - {response.text}")
                self._circuit_breaker.record_failure()
                response.raise_for_status()

            data = response.json()

            self._access_token = data["access_token"]
            self._token_expiry = time.time() + data.get("expires_in", 3600)

            self._circuit_breaker.record_success()
            self.logger.debug("Obtained new Zoom access token")
            return self._access_token

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to get Zoom access token: {e}")
            self._circuit_breaker.record_failure()
            raise

    def _get_admin_token(self) -> Optional[str]:
        """
        Get Server-to-Server OAuth token for admin API calls.

        Uses account_credentials grant type which is required for
        user:read:admin and other admin scopes.

        Returns:
            Access token string or None if S2S credentials not configured
        """
        if not self.s2s_client_id or not self.s2s_client_secret:
            self.logger.warning("S2S credentials not configured - cannot get admin token")
            return None

        # Return cached token if still valid
        if self._admin_token and time.time() < self._admin_token_expiry - 60:
            return self._admin_token

        auth_header = base64.b64encode(
            f"{self.s2s_client_id}:{self.s2s_client_secret}".encode()
        ).decode()

        try:
            # Server-to-Server OAuth uses account_credentials grant
            response = requests.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "account_credentials",
                    "account_id": self.s2s_account_id,
                },
                timeout=10
            )

            if response.status_code != 200:
                self.logger.error(f"Admin token request failed: {response.status_code} - {response.text}")
                return None

            data = response.json()
            self._admin_token = data["access_token"]
            self._admin_token_expiry = time.time() + data.get("expires_in", 3600)

            self.logger.debug("Obtained new Zoom admin token")
            return self._admin_token

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to get Zoom admin token: {e}")
            return None

    def _sanitize_message(self, message: str, max_length: int = 4000) -> str:
        """
        Sanitize message for Zoom API compatibility.

        - Removes unsupported markdown (horizontal rules)
        - Strips problematic unicode characters
        - Truncates to max length
        """
        if not message:
            return message

        # Remove horizontal rules (---) which Zoom doesn't support
        import re
        message = re.sub(r'\n---+\n', '\n\n', message)
        message = re.sub(r'^---+$', '', message, flags=re.MULTILINE)

        # Remove any remaining non-ASCII characters that might cause issues
        # Keep basic latin, numbers, punctuation, and common symbols
        cleaned = []
        for char in message:
            if ord(char) < 128 or char in '\n\r\t':
                cleaned.append(char)
            elif char in '—–''""…•':
                # Replace smart quotes and dashes with ASCII equivalents
                replacements = {'—': '-', '–': '-', ''': "'", ''': "'",
                               '"': '"', '"': '"', '…': '...', '•': '*'}
                cleaned.append(replacements.get(char, ' '))
        message = ''.join(cleaned)

        # Clean up multiple newlines
        message = re.sub(r'\n{3,}', '\n\n', message)

        # Truncate if too long
        if len(message) > max_length:
            message = message[:max_length - 50] + '\n\n... (truncated)'

        return message.strip()

    def send_message(
        self,
        to_jid: str,
        message: str,
        robot_jid: str = None,
        account_id: str = None,
        user_jid: str = None,
        is_markdown: bool = True
    ) -> bool:
        """
        Send a message to a Zoom Team Chat user or channel.

        Args:
            to_jid: Recipient JID (user or channel)
            message: Message text to send
            robot_jid: Bot JID (defaults to self.bot_jid)
            account_id: Account ID (defaults to self.account_id)
            user_jid: User JID on whose behalf message is sent (required by API)
            is_markdown: Whether to parse message as markdown

        Returns:
            True if message sent successfully
        """
        if not message:
            return True

        # Sanitize message for Zoom API compatibility
        message = self._sanitize_message(message)

        robot_jid = robot_jid or self.bot_jid
        account_id = account_id or self.account_id

        if not robot_jid:
            self.logger.error("Bot JID not configured")
            return False

        try:
            token = self._get_access_token()

            # Zoom Chatbot API message format
            # See: https://developers.zoom.us/docs/api/chatbot/
            # Required fields: robot_jid, to_jid, account_id, user_jid, content
            payload = {
                "robot_jid": robot_jid,
                "to_jid": to_jid,
                "account_id": account_id,
                "content": {
                    "head": {
                        "text": "QA Bot"
                    },
                    "body": [
                        {
                            "type": "message",
                            "text": message
                        }
                    ]
                }
            }

            # Add user_jid if provided (required by API)
            if user_jid:
                payload["user_jid"] = user_jid

            self.logger.debug(f"Sending message to: {to_jid[:20]}... (robot_jid={robot_jid[:20] if robot_jid else 'None'})")

            response = requests.post(
                self.CHATBOT_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10
            )

            if response.status_code == 201:
                self._circuit_breaker.record_success()
                self.logger.info(f"Message sent to {to_jid[:20]}...")
                return True
            else:
                self._circuit_breaker.record_failure()
                self.logger.error(
                    f"Failed to send message: {response.status_code} - {response.text}"
                )
                self.logger.error(f"Payload was: robot_jid={robot_jid}, to_jid={to_jid}, account_id={account_id}")
                return False

        except requests.exceptions.RequestException as e:
            self._circuit_breaker.record_failure()
            self.logger.error(f"Error sending Zoom message: {e}")
            return False

    def send_card(
        self,
        to_jid: str,
        header: str,
        body: str,
        actions: list = None,
        robot_jid: str = None,
        account_id: str = None
    ) -> bool:
        """
        Send a rich card message to Zoom Team Chat.

        Args:
            to_jid: Recipient JID
            header: Card header text
            body: Card body text
            actions: List of action buttons
            robot_jid: Bot JID
            account_id: Account ID

        Returns:
            True if sent successfully
        """
        robot_jid = robot_jid or self.bot_jid
        account_id = account_id or self.account_id

        try:
            token = self._get_access_token()

            content_body = [
                {
                    "type": "section",
                    "sidebar_color": "#0E71EB",  # Zoom blue
                    "sections": [
                        {
                            "type": "message",
                            "text": f"**{header}**\n\n{body}",
                            "is_markdown_support": True
                        }
                    ]
                }
            ]

            if actions:
                content_body.append({
                    "type": "actions",
                    "items": actions
                })

            payload = {
                "robot_jid": robot_jid,
                "to_jid": to_jid,
                "account_id": account_id,
                "content": {
                    "body": content_body
                }
            }

            response = requests.post(
                self.CHATBOT_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10
            )

            if response.status_code == 201:
                self._circuit_breaker.record_success()
                return True
            else:
                self._circuit_breaker.record_failure()
                return False

        except requests.exceptions.RequestException as e:
            self._circuit_breaker.record_failure()
            self.logger.error(f"Error sending Zoom card: {e}")
            return False

    def get_user_email(self, user_id: str) -> Optional[str]:
        """
        Get a Zoom user's email address from their user ID.

        Uses the Zoom Users API to fetch user details.
        Requires Server-to-Server OAuth with user:read:user:admin scope.
        Results are cached to avoid repeated API calls.

        Args:
            user_id: Zoom user ID (e.g., from webhook payload)

        Returns:
            User's email address, or None if not found
        """
        if not user_id:
            return None

        # Check cache first
        cache_key = f"_user_email_{user_id}"
        if hasattr(self, cache_key):
            cached = getattr(self, cache_key)
            if cached.get("expiry", 0) > time.time():
                return cached.get("email")

        # Check circuit breaker
        if not self._circuit_breaker.can_execute():
            self.logger.warning("Zoom API circuit breaker open - cannot fetch user email")
            return None

        try:
            # Use admin token for user data access (requires account_credentials grant)
            token = self._get_admin_token()
            if not token:
                self.logger.warning("No admin token available for user lookup")
                return None

            response = requests.get(
                f"https://api.zoom.us/v2/users/{user_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                },
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                email = data.get("email")

                # Cache for 1 hour
                setattr(self, cache_key, {
                    "email": email,
                    "expiry": time.time() + 3600
                })

                self._circuit_breaker.record_success()
                self.logger.debug(f"Fetched email for user {user_id}: {email}")
                return email

            elif response.status_code == 404:
                # 404 is not a service failure, don't record as circuit failure
                self.logger.warning(f"Zoom user not found: {user_id}")
                return None
            else:
                self._circuit_breaker.record_failure()
                self.logger.warning(
                    f"Failed to get Zoom user {user_id}: {response.status_code}"
                )
                return None

        except requests.exceptions.RequestException as e:
            self._circuit_breaker.record_failure()
            self.logger.error(f"Error fetching Zoom user email: {e}")
            return None

    def get_circuit_status(self) -> dict:
        """Get circuit breaker status for health checks."""
        return self._circuit_breaker.get_status()
