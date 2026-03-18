"""
Authentication service.

Handles verification of incoming webhooks from:
- Zoom Team Chat
- Recall.ai transcription webhooks
- n8n callbacks

Also handles role-based authorization for sensitive operations
like intern onboarding/offboarding.
"""

import hashlib
import hmac
import time
from typing import Optional
import logging


class AuthService:
    """
    Service for webhook authentication.

    Supports multiple authentication methods:
    - HMAC signature verification (recommended)
    - Bearer token in header
    - Token in request body
    """

    # Maximum age for webhook timestamps (5 minutes)
    MAX_TIMESTAMP_AGE_SECONDS = 300

    def __init__(
        self,
        zoom_token: Optional[str] = None,
        zoom_secret: Optional[str] = None,
        recall_secret: Optional[str] = None,
        n8n_secret: Optional[str] = None,
        api_key: Optional[str] = None,
        authorized_onboarding_users: Optional[list[str]] = None,
        allowed_email_domains: Optional[list[str]] = None,
        require_production_auth: bool = True,
        logger: Optional[logging.Logger] = None
    ):
        self.zoom_token = zoom_token
        self.zoom_secret = zoom_secret
        self.recall_secret = recall_secret
        self.n8n_secret = n8n_secret
        self.api_key = api_key  # For internal API endpoints
        self.require_production_auth = require_production_auth
        self.logger = logger or logging.getLogger(__name__)

        # Role-based authorization for sensitive operations
        self.authorized_onboarding_users = authorized_onboarding_users or []
        self.allowed_email_domains = allowed_email_domains or []

    def _get_header(self, headers: dict, key: str) -> Optional[str]:
        """Get header value with case-insensitive lookup."""
        key_lower = key.lower()
        for k, v in headers.items():
            if k.lower() == key_lower:
                return v
        return None

    def verify_zoom_request(
        self,
        headers: dict,
        body: str,
        data: dict
    ) -> bool:
        """
        Verify that a request is from Zoom.

        Supports:
        1. HMAC signature verification (x-zm-signature header)
        2. Bearer token in Authorization header
        3. Token in request body

        Args:
            headers: Request headers dict
            body: Raw request body string
            data: Parsed JSON data

        Returns:
            True if verified, False otherwise
        """
        if not self.zoom_token and not self.zoom_secret:
            # No auth configured - only allow in explicit dev mode
            if self.require_production_auth:
                # SECURITY: Fail-secure in production mode
                self.logger.error(
                    "SECURITY: Zoom webhook rejected - no auth credentials configured "
                    "and require_production_auth=True"
                )
                return False
            else:
                # Dev mode explicitly allowed
                self.logger.warning("No Zoom auth configured - running in dev mode (require_production_auth=False)")
                return True

        # Method 1: HMAC signature verification (preferred)
        signature = self._get_header(headers, "x-zm-signature")
        timestamp = self._get_header(headers, "x-zm-request-timestamp")

        if signature and timestamp and self.zoom_secret and body:
            try:
                # Validate timestamp is recent (prevent replay attacks)
                ts = int(timestamp)
                now = int(time.time())
                if abs(now - ts) > self.MAX_TIMESTAMP_AGE_SECONDS:
                    self.logger.warning(f"Timestamp too old: {abs(now - ts)}s > {self.MAX_TIMESTAMP_AGE_SECONDS}s")
                    return False

                message = f"v0:{timestamp}:{body}"
                expected_sig = "v0=" + hmac.new(
                    self.zoom_secret.encode(),
                    message.encode(),
                    hashlib.sha256
                ).hexdigest()

                if hmac.compare_digest(signature, expected_sig):
                    return True
                else:
                    self.logger.warning("HMAC signature mismatch")
            except ValueError:
                self.logger.error(f"Invalid timestamp format: {timestamp}")
            except Exception as e:
                self.logger.error(f"HMAC verification error: {e}")

        # Method 2: Bearer token in header
        if self.zoom_token:
            auth_header = self._get_header(headers, "Authorization") or ""
            if auth_header.replace("Bearer ", "") == self.zoom_token:
                return True

            # Token in body
            if data.get("token") == self.zoom_token:
                return True

        return False

    def verify_recall_signature(
        self,
        headers: dict,
        body: bytes
    ) -> bool:
        """
        Verify Recall.ai webhook signature.

        Recall.ai uses Svix-style webhooks with these headers:
        - Webhook-Id: Unique message identifier
        - Webhook-Timestamp: Unix timestamp
        - Webhook-Signature: v1,{base64_encoded_hmac}

        The secret has format "whsec_{base64_key}" - strip prefix and decode.
        Signing string is: {msgId}.{timestamp}.{body}

        Args:
            headers: Request headers dict
            body: Raw request body bytes

        Returns:
            True if verified or no secret configured
        """
        import base64

        if not self.recall_secret:
            # No auth configured - only allow in explicit dev mode
            if self.require_production_auth:
                # SECURITY: Fail-secure in production mode
                self.logger.error(
                    "SECURITY: Recall webhook rejected - no secret configured "
                    "and require_production_auth=True"
                )
                return False
            else:
                # Dev mode explicitly allowed
                self.logger.warning("No Recall secret configured - accepting without verification (require_production_auth=False)")
                return True

        # Get Svix-style headers (Recall.ai uses these)
        msg_id = self._get_header(headers, "Webhook-Id")
        timestamp = self._get_header(headers, "Webhook-Timestamp")
        signature_header = self._get_header(headers, "Webhook-Signature")

        # Fall back to legacy headers if Svix headers not present
        if not signature_header:
            signature_header = self._get_header(headers, "X-Recall-Signature")
        if not timestamp:
            timestamp = self._get_header(headers, "X-Recall-Timestamp")

        # If still no signature, try simple secret header (legacy)
        if not signature_header:
            simple_secret = self._get_header(headers, "X-Transcription-Secret")
            if simple_secret and hmac.compare_digest(simple_secret, self.recall_secret):
                return True
            self.logger.warning("Recall webhook rejected: No signature header (Webhook-Signature or X-Recall-Signature)")
            return False

        # SECURITY: Require timestamp for signature-based verification (prevent replay attacks)
        if not timestamp:
            if self.require_production_auth:
                self.logger.error(
                    "SECURITY: Recall webhook rejected - timestamp header missing "
                    "and require_production_auth=True (replay attack prevention)"
                )
                return False
            else:
                self.logger.warning("Recall timestamp missing - allowing in dev mode (require_production_auth=False)")
        else:
            # Validate timestamp freshness
            try:
                ts = int(timestamp)
                now = int(time.time())
                if abs(now - ts) > self.MAX_TIMESTAMP_AGE_SECONDS:
                    self.logger.warning(f"Recall timestamp too old: {abs(now - ts)}s")
                    return False
            except ValueError:
                self.logger.warning(f"Invalid Recall timestamp: {timestamp}")
                if self.require_production_auth:
                    return False

        # Prepare the secret key
        # Recall.ai secrets are formatted as "whsec_{base64_key}"
        secret_key = self.recall_secret
        if secret_key.startswith("whsec_"):
            try:
                secret_key = base64.b64decode(secret_key[6:])
            except Exception as e:
                self.logger.warning(f"Failed to decode whsec_ secret: {e}, using raw secret")
                secret_key = self.recall_secret.encode()
        else:
            secret_key = self.recall_secret.encode()

        # Build signing string: {msgId}.{timestamp}.{body}
        body_str = body.decode('utf-8') if isinstance(body, bytes) else body
        if msg_id and timestamp:
            signing_string = f"{msg_id}.{timestamp}.{body_str}"
        else:
            # Legacy format - just body
            signing_string = body_str

        # Compute expected signature
        try:
            expected_bytes = hmac.new(
                secret_key if isinstance(secret_key, bytes) else secret_key.encode(),
                signing_string.encode(),
                hashlib.sha256
            ).digest()
            expected_b64 = base64.b64encode(expected_bytes).decode()

            # Parse signature header - format is "v1,{base64sig}" or space-separated list
            signatures = signature_header.split(" ")
            for sig in signatures:
                if sig.startswith("v1,"):
                    sig_value = sig[3:]  # Remove "v1," prefix
                    if hmac.compare_digest(sig_value, expected_b64):
                        return True
                # Also try raw comparison (legacy hex format)
                expected_hex = hmac.new(
                    secret_key if isinstance(secret_key, bytes) else secret_key.encode(),
                    signing_string.encode(),
                    hashlib.sha256
                ).hexdigest()
                if hmac.compare_digest(sig.lstrip("v1,"), expected_hex):
                    return True

            self.logger.warning("Recall webhook rejected: Signature mismatch")
            self.logger.debug(f"Headers: msg_id={msg_id}, timestamp={timestamp}")
            return False

        except Exception as e:
            self.logger.error(f"Recall signature verification error: {e}")
            return False

    def verify_api_key(self, headers: dict) -> bool:
        """
        Verify API key for internal endpoints.

        Args:
            headers: Request headers dict

        Returns:
            True if API key matches. False if no key configured in production mode.
        """
        if not self.api_key:
            if self.require_production_auth:
                self.logger.warning("API request rejected: API_KEY not configured (production mode)")
                return False
            # Dev mode only - allow without key
            self.logger.debug("API request allowed: dev mode (no API_KEY configured)")
            return True

        auth_header = self._get_header(headers, "Authorization") or ""
        api_key_header = self._get_header(headers, "X-API-Key")

        # Check Bearer token
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if hmac.compare_digest(token, self.api_key):
                return True

        # Check X-API-Key header
        if api_key_header and hmac.compare_digest(api_key_header, self.api_key):
            return True

        return False

    def verify_n8n_callback(
        self,
        headers: dict,
        data: dict
    ) -> bool:
        """
        Verify n8n callback request.

        Args:
            headers: Request headers dict
            data: Parsed JSON data

        Returns:
            True if verified or no secret configured
        """
        if not self.n8n_secret:
            return True

        # Check header first
        header_secret = self._get_header(headers, "X-Callback-Secret")
        if header_secret == self.n8n_secret:
            return True

        # Check body
        body_secret = data.get("secret")
        return body_secret == self.n8n_secret

    def create_zoom_challenge_response(
        self,
        plain_token: str
    ) -> dict:
        """
        Create response for Zoom URL validation challenge.

        Args:
            plain_token: The plainToken from Zoom's challenge

        Returns:
            Dict with plainToken and encryptedToken
        """
        if self.zoom_secret:
            encrypted = hmac.new(
                self.zoom_secret.encode(),
                plain_token.encode(),
                hashlib.sha256
            ).hexdigest()
        else:
            encrypted = plain_token

        return {
            "plainToken": plain_token,
            "encryptedToken": encrypted
        }

    # =========================================================================
    # Role-Based Authorization
    # =========================================================================

    def can_manage_interns(
        self,
        user_id: str,
        user_email: Optional[str] = None
    ) -> bool:
        """
        Check if user is authorized for onboarding/offboarding operations.

        Authorization is granted if ANY of:
        1. User ID is in the authorized_onboarding_users allowlist
        2. User email domain is in allowed_email_domains

        Args:
            user_id: Zoom user ID (e.g., from webhook payload)
            user_email: Optional user email for domain-based auth

        Returns:
            True if user is authorized for intern management
        """
        # Check allowlist first (most specific)
        if user_id in self.authorized_onboarding_users:
            self.logger.debug(f"User {user_id} authorized via allowlist")
            return True

        # Check email domain
        if user_email and self.allowed_email_domains:
            email_lower = user_email.lower()
            for domain in self.allowed_email_domains:
                if email_lower.endswith(f"@{domain.lower()}"):
                    self.logger.debug(f"User {user_id} authorized via email domain: {domain}")
                    return True

        self.logger.info(f"User {user_id} not authorized for intern management")
        return False

    def get_authorization_status(
        self,
        user_id: str,
        user_email: Optional[str] = None
    ) -> dict:
        """
        Get detailed authorization status for a user.

        Args:
            user_id: Zoom user ID
            user_email: Optional user email

        Returns:
            Dict with authorization details
        """
        authorized = self.can_manage_interns(user_id, user_email)
        return {
            "user_id": user_id,
            "user_email": user_email,
            "can_manage_interns": authorized,
            "in_allowlist": user_id in self.authorized_onboarding_users,
            "email_domain_allowed": (
                user_email and
                any(
                    user_email.lower().endswith(f"@{d.lower()}")
                    for d in self.allowed_email_domains
                )
            ) if user_email else False,
            "allowlist_configured": len(self.authorized_onboarding_users) > 0,
            "domain_filter_configured": len(self.allowed_email_domains) > 0,
        }
