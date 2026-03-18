"""
Zoom webhook and chat endpoints.

Handles incoming Zoom Team Chat webhooks and message processing.
"""

import hashlib
import hmac
import json
import re
import time
import uuid
from flask import Blueprint, request, jsonify, current_app, g

from ..config import get_config, BOT_MENTIONS
from ..utils import is_duplicate_message
from ..middleware import verify_zoom_request

zoom_bp = Blueprint("zoom", __name__)


def _get_audit_repository():
    """Get AuditRepository from app context."""
    if hasattr(current_app, 'audit_repository') and current_app.audit_repository:
        return current_app.audit_repository
    from ..repositories import AuditRepository
    return AuditRepository(db_path=current_app.config["DB_PATH"])


_config = get_config()

# Regex pattern for meeting URLs
MEETING_URL_PATTERN = re.compile(
    r'https?://[^\s]*(?:zoom\.us|teams\.microsoft\.com|teams\.live\.com|meet\.google\.com)[^\s]*',
    re.IGNORECASE
)

# Message deduplication: Use shared thread-safe utility from utils
# Removed local implementation to centralize and ensure thread-safety


def _sanitize_input(text: str, max_length: int = None) -> str:
    """Sanitize user input using QueryService."""
    if hasattr(current_app, 'query_service') and current_app.query_service:
        return current_app.query_service.sanitize_input(text, max_length)

    # Minimal fallback for edge cases (empty input)
    if not text:
        return ""
    return text.strip()[:max_length or 2000]


def _handle_zoom_challenge(data: dict):
    """Handle Zoom URL validation challenge."""
    import hashlib
    import hmac

    plain_token = data.get("payload", {}).get("plainToken", "")
    secret = current_app.config.get("ZOOM_BOT_SECRET", "")

    encrypted = hmac.new(
        secret.encode(),
        plain_token.encode(),
        hashlib.sha256
    ).hexdigest()

    current_app.logger.info(f"[{g.request_id}] Handled Zoom URL validation challenge")

    return jsonify({
        "plainToken": plain_token,
        "encryptedToken": encrypted
    })


def _check_rate_limit(user_id: str) -> bool:
    """
    Check if user is within rate limits using RateLimitService.

    Returns True if OK, False if rate limited.
    """
    if hasattr(current_app, 'rate_limit_service') and current_app.rate_limit_service:
        rate_limit = current_app.config.get("RATE_LIMIT", 20)
        return current_app.rate_limit_service.check_chat_limit(user_id, rate_limit)

    # Service unavailable - allow request but log warning
    current_app.logger.warning(f"[{g.request_id}] RateLimitService unavailable, allowing request")
    return True


def _extract_meeting_url(text: str) -> str | None:
    """Extract a meeting URL from the message text if present."""
    match = MEETING_URL_PATTERN.search(text)
    return match.group(0) if match else None


def _handle_meeting_join_request(meeting_url: str, user_id: str, user_name: str, request_id: str) -> str:
    """
    Handle a request to join a meeting via chat.

    Delegates to MeetingService for consistent behavior with avatar endpoints.

    Returns a response message to send back to the user.
    """
    # Use MeetingService if available
    if hasattr(current_app, 'meeting_service') and current_app.meeting_service:
        try:
            result = current_app.meeting_service.join_meeting_for_chat(
                meeting_url=meeting_url,
                user_id=user_id,
                user_name=user_name,
                request_id=request_id
            )
            current_app.logger.info(
                f"[{request_id}] Bot joining meeting via chat (using MeetingService) "
                f"(requested by {user_name})"
            )
            return result
        except Exception as e:
            current_app.logger.error(f"[{request_id}] Chat meeting join error: {e}", exc_info=True)
            return f"Sorry, I couldn't join the meeting: {str(e)}"

    # Fallback if MeetingService not configured
    if not current_app.meeting_handler:
        return "Meeting integration is not configured. I can't join meetings right now."

    return "Meeting service not fully configured. Please try the API endpoint."


@zoom_bp.route("/oauth/callback", methods=["GET"])
def oauth_callback():
    """
    Handle Zoom OAuth callback during app installation.

    When a user adds the app from Zoom Marketplace, Zoom redirects here
    with an authorization code. For Team Chat bots using Server-to-Server
    OAuth, we just acknowledge the installation.
    """
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        current_app.logger.error(f"[{g.request_id}] OAuth error: {error}")
        return f"""
        <html>
        <head><title>QA Bot - Installation Failed</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>Installation Failed</h1>
            <p>Error: {error}</p>
            <p>Please try again or contact support.</p>
        </body>
        </html>
        """, 400

    if code:
        current_app.logger.info(f"[{g.request_id}] OAuth callback received, code present")

        # For Server-to-Server OAuth bots, we don't need to exchange the code
        # The bot uses client_credentials grant for API access
        # This callback just acknowledges the app was installed

        return """
        <html>
        <head><title>QA Bot - Installed</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>QA Bot Installed Successfully!</h1>
            <p>You can now use QA Bot in your Zoom Team Chat.</p>
            <p>Try messaging the bot with <code>help</code> to get started.</p>
            <p style="margin-top: 30px; color: #666;">You can close this window.</p>
        </body>
        </html>
        """

    # No code or error - unexpected state
    current_app.logger.warning(f"[{g.request_id}] OAuth callback with no code or error")
    return """
    <html>
    <head><title>QA Bot</title></head>
    <body style="font-family: sans-serif; text-align: center; padding: 50px;">
        <h1>QA Bot</h1>
        <p>This is the OAuth callback endpoint.</p>
        <p>To install the bot, use the Zoom Marketplace.</p>
    </body>
    </html>
    """


@zoom_bp.route("/zoom/webhook", methods=["POST"])
def handle_zoom_webhook():
    """Handle incoming Zoom Team Chat webhooks."""
    raw_body = request.get_data(as_text=True)
    data = request.json or {}
    request_id = g.request_id

    # Handle URL validation challenge
    if data.get("event") == "endpoint.url_validation":
        return _handle_zoom_challenge(data)

    # Verify request
    if not verify_zoom_request(data, raw_body):
        current_app.logger.warning(f"[{request_id}] Unauthorized webhook request")
        return jsonify({"error": "unauthorized"}), 401

    # Extract message details - handle both direct messages and channel messages
    payload = data.get("payload", {})
    obj = payload.get("object", {})

    # For channel messages, data is nested in 'object' and to_jid contains @conference
    # For direct messages via new format, obj exists but to_jid is a user JID
    # For direct messages via legacy format, data is at top level of payload
    obj_to_jid = obj.get("to_jid", "") if obj else ""
    is_channel_message = obj and obj_to_jid and "@conference" in obj_to_jid

    if is_channel_message:
        # Channel message format
        message_id = obj.get("message_id", "")
        text = _sanitize_input(obj.get("message", "") or payload.get("cmd", ""))
        user_id = payload.get("operator_id", "unknown")
        sender = obj.get("from", "")
        user_name = _sanitize_input(sender if isinstance(sender, str) else sender.get("name", "") or payload.get("operator", "Unknown User"), max_length=50)
        to_jid = obj.get("to_jid", "")
        user_jid = payload.get("operator_jid", "")
        account_id = payload.get("account_id", "")
        current_app.logger.info(f"[{request_id}] Channel message: to_jid={to_jid[:30]}..., user={user_name}")
    elif obj and obj_to_jid:
        # Direct message format (new format with object)
        message_id = obj.get("message_id", "")
        text = _sanitize_input(obj.get("message", "") or payload.get("cmd", ""))
        user_id = payload.get("operator_id", "unknown")
        sender = obj.get("from", "")
        user_name = _sanitize_input(sender if isinstance(sender, str) else sender.get("name", "") or payload.get("operator", "Unknown User"), max_length=50)
        to_jid = obj_to_jid
        user_jid = payload.get("operator_jid", "")
        account_id = payload.get("account_id", "")
        current_app.logger.info(f"[{request_id}] Direct message (new): to_jid={to_jid[:30]}..., user={user_name}")
    else:
        # Direct message format (legacy)
        message_id = payload.get("messageId") or payload.get("msgId") or ""
        text = _sanitize_input(payload.get("cmd", "") or payload.get("text", ""))
        user_id = payload.get("userId", "unknown")
        user_name = _sanitize_input(payload.get("userName", "Unknown User"), max_length=50)
        to_jid = payload.get("toJid", "")
        user_jid = payload.get("userJid", "")
        account_id = payload.get("accountId", "")

    # Deduplication check (uses thread-safe shared utility)
    if not current_app.config.get("TESTING"):
        dedup_key = message_id or f"{user_id}:{text}"
        if is_duplicate_message(dedup_key):
            current_app.logger.info(f"[{request_id}] Duplicate message ignored")
            return jsonify({"status": "duplicate ignored"}), 200

    current_app.logger.info(f"[{request_id}] Query from {user_name[:10]}...: {text[:50]}...")

    # Check rate limit
    if not _check_rate_limit(user_id):
        current_app.logger.warning(f"[{request_id}] Rate limit exceeded for {user_id}")
        return jsonify({
            "text": "You've reached the query limit (20/hour). Please wait before trying again."
        })

    # Check for meeting URL - if found, join the meeting
    # Use the original text from payload (before sanitization) to preserve URL
    # For channel messages, text is in obj.get("message")
    original_text = obj.get("message", "") or payload.get("cmd", "") or payload.get("text", "")
    meeting_url = _extract_meeting_url(original_text)
    if meeting_url:
        current_app.logger.info(f"[{request_id}] Meeting URL detected: {meeting_url[:50]}...")
        response_text = _handle_meeting_join_request(meeting_url, user_id, user_name, request_id)

        # Send response via Zoom chatbot
        if current_app.zoom_chatbot and to_jid:
            try:
                current_app.zoom_chatbot.send_message(
                    message=response_text,
                    to_jid=to_jid,
                    account_id=account_id or current_app.config.get("ZOOM_ACCOUNT_ID", ""),
                    user_jid=user_jid,
                )
            except Exception as e:
                current_app.logger.error(f"[{request_id}] Failed to send via Zoom API: {e}")

        return jsonify({"text": response_text})

    # Fetch user email from Zoom for domain-based authorization
    user_email = ""
    if current_app.zoom_chatbot and user_id:
        user_email = current_app.zoom_chatbot.get_user_email(user_id) or ""

    # Process the query using consolidated QueryService
    try:
        response_text = _process_query(text, user_name, request_id, user_id=user_id, channel_id=to_jid, user_email=user_email)

        # Send response via Zoom chatbot
        if current_app.zoom_chatbot and to_jid:
            try:
                current_app.zoom_chatbot.send_message(
                    message=response_text,
                    to_jid=to_jid,
                    account_id=account_id or current_app.config.get("ZOOM_ACCOUNT_ID", ""),
                    user_jid=user_jid,
                )
                current_app.logger.info(f"[{request_id}] Sent response via Zoom API")
            except Exception as e:
                current_app.logger.error(f"[{request_id}] Failed to send via Zoom API: {e}")

        # Log the query
        elapsed_ms = int((time.time() - g.start_time) * 1000) if hasattr(g, 'start_time') else 0
        if hasattr(current_app, 'query_log_repository') and current_app.query_log_repository:
            current_app.query_log_repository.log_query(user_id, "brain", text, elapsed_ms)
        else:
            # Fallback to database function
            from ..database import log_query
            db_path = current_app.config.get("DB_PATH")
            if db_path:
                log_query(db_path, user_id, "brain", text, elapsed_ms)

        return jsonify({"text": response_text})

    except Exception as e:
        current_app.logger.error(f"[{request_id}] Query processing error: {e}", exc_info=True)
        return jsonify({"text": "Sorry, something went wrong. Try `help` for available commands."})


def _process_query(text: str, user_name: str, request_id: str, user_id: str = "", channel_id: str = "", user_email: str = "") -> str:
    """
    Process a user query using QueryService.

    Args:
        text: User's query (already sanitized)
        user_name: User display name
        request_id: Request ID for logging
        user_id: User identifier
        channel_id: Zoom channel ID
        user_email: User email (for domain-based authorization)

    Returns:
        Response text
    """
    # Use QueryService if available (consolidated query processing)
    if hasattr(current_app, 'query_service') and current_app.query_service:
        return current_app.query_service.process_query(
            text=text,
            user_id=user_id,
            user_name=user_name,
            channel_id=channel_id,
            user_email=user_email,
            request_id=request_id
        )

    # Fallback: direct brain/parser usage if service not available
    if current_app.qa_brain:
        response = current_app.qa_brain.chat_query(text, user_name)
        current_app.logger.info(
            f"[{request_id}] Brain response: capability={response.capability.value}, "
            f"confidence={response.confidence:.2f}, latency={response.latency_ms}ms"
        )
        return response.response

    if current_app.query_parser:
        result = current_app.query_parser.parse(text)
        current_app.logger.info(f"[{request_id}] Parser result: type={result.query_type.value}")

        if current_app.response_builder:
            return current_app.response_builder.format_help()

    return "I'm not sure how to help with that. Type `help` for available commands."


@zoom_bp.route("/api/query", methods=["POST"])
def api_query():
    """Direct API query endpoint (for testing/n8n). Requires API key authentication."""
    # Verify API key
    if hasattr(current_app, 'auth_service') and current_app.auth_service:
        if not current_app.auth_service.verify_api_key(dict(request.headers)):
            current_app.logger.warning(f"[{g.request_id}] Unauthorized API query attempt")
            return jsonify({"error": "Unauthorized - API key required"}), 401

    data = request.json or {}
    text = _sanitize_input(data.get("query", ""))
    user_name = data.get("user_name", "API User")
    user_id = data.get("user_id", "api")

    if not text:
        return jsonify({"error": "Query is required"}), 400

    try:
        response_text = _process_query(text, user_name, g.request_id, user_id=user_id)
        return jsonify({"response": response_text})
    except Exception as e:
        current_app.logger.error(f"API query error: {e}", exc_info=True)
        return jsonify({"error": "Query processing failed"}), 500


@zoom_bp.route("/api/zoom/send", methods=["POST"])
def api_zoom_send():
    """Send a message to Zoom (for n8n workflows). Requires API key authentication."""
    # Verify API key
    if hasattr(current_app, 'auth_service') and current_app.auth_service:
        if not current_app.auth_service.verify_api_key(dict(request.headers)):
            current_app.logger.warning(f"[{g.request_id}] Unauthorized Zoom send attempt")
            return jsonify({"error": "Unauthorized - API key required"}), 401

    data = request.json or {}
    message = data.get("message", "")
    channel = data.get("channel", "general")

    if not message:
        return jsonify({"error": "Message is required"}), 400

    if current_app.zoom_chatbot:
        try:
            # Use channel JID if configured, fallback to bot JID
            target_jid = current_app.config.get("ZOOM_DEFAULT_CHANNEL_JID") or current_app.config.get("ZOOM_BOT_JID", "")
            current_app.zoom_chatbot.send_message(
                message=message,
                to_jid=target_jid,
                account_id=current_app.config.get("ZOOM_ACCOUNT_ID", ""),
            )
            current_app.logger.info(f"[{g.request_id}] n8n sent Zoom message: {message[:50]}...")
            return jsonify({
                "status": "sent",
                "channel": channel,
                "message_preview": message[:100]
            })
        except Exception as e:
            current_app.logger.error(f"[{g.request_id}] Failed to send Zoom message: {e}")
            return jsonify({"error": str(e)}), 500
    else:
        current_app.logger.info(f"[{g.request_id}] n8n message (no Zoom): [{channel}] {message}")
        return jsonify({
            "status": "logged",
            "channel": channel,
            "message_preview": message[:100],
            "note": "Zoom chatbot not configured - message logged only"
        })


@zoom_bp.route("/api/cache/refresh", methods=["POST"])
def refresh_cache():
    """Force refresh the issue cache. Requires API key authentication."""
    # Verify API key
    if hasattr(current_app, 'auth_service') and current_app.auth_service:
        if not current_app.auth_service.verify_api_key(dict(request.headers)):
            current_app.logger.warning(f"[{g.request_id}] Unauthorized cache refresh attempt")
            return jsonify({"error": "Unauthorized - API key required"}), 401

    if current_app.issue_cache:
        try:
            current_app.issue_cache.refresh()
            return jsonify({"status": "refreshed"})
        except Exception as e:
            current_app.logger.error(f"Cache refresh error: {e}", exc_info=True)
            return jsonify({"error": "Failed to refresh cache"}), 500
    return jsonify({"error": "Cache not configured"}), 503


@zoom_bp.route("/api/stats", methods=["GET"])
def get_stats():
    """Get query statistics. Requires API key authentication."""
    # Verify API key
    if hasattr(current_app, 'auth_service') and current_app.auth_service:
        if not current_app.auth_service.verify_api_key(dict(request.headers)):
            current_app.logger.warning(f"[{g.request_id}] Unauthorized stats request")
            return jsonify({"error": "Unauthorized - API key required"}), 401

    try:
        if hasattr(current_app, 'query_log_repository') and current_app.query_log_repository:
            stats = current_app.query_log_repository.get_stats()
        else:
            # Fallback to database function
            from ..database import get_query_stats
            db_path = current_app.config.get("DB_PATH")
            stats = get_query_stats(db_path) if db_path else {}
        return jsonify(stats)
    except Exception as e:
        current_app.logger.error(f"Stats error: {e}", exc_info=True)
        return jsonify({"error": "Failed to get stats"}), 500


@zoom_bp.route("/api/zoom/meetings/register", methods=["POST"])
def register_for_meetings():
    """
    Register a user for recurring Zoom meetings. Requires API key authentication.

    Called by n8n onboarding workflow to add interns to DevOps meetings.

    JSON body:
        email: User's email address (required)
        first_name: User's first name (required)
        last_name: User's last name (optional)
        meeting_ids: List of meeting IDs (optional, uses defaults if not provided)
        intern_id: Intern ID for audit logging (optional)

    Returns:
        success: Overall success status
        meetings: List of successful registrations
        errors: List of failed registrations
    """
    # Verify API key
    if hasattr(current_app, 'auth_service') and current_app.auth_service:
        if not current_app.auth_service.verify_api_key(dict(request.headers)):
            current_app.logger.warning(f"[{g.request_id}] Unauthorized meeting registration attempt")
            return jsonify({"error": "Unauthorized - API key required"}), 401

    if not hasattr(current_app, 'zoom_meetings') or not current_app.zoom_meetings:
        return jsonify({
            "success": False,
            "error": "Zoom Meetings client not configured"
        }), 503

    data = request.json or {}
    email = data.get("email", "").strip()
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    meeting_ids = data.get("meeting_ids")
    intern_id = data.get("intern_id")

    if not email:
        return jsonify({
            "success": False,
            "error": "email is required"
        }), 400

    if not first_name:
        return jsonify({
            "success": False,
            "error": "first_name is required"
        }), 400

    # Use default meeting IDs from config if not provided
    if not meeting_ids:
        meeting_ids = _config.onboarding.zoom_meeting_ids

    if not meeting_ids:
        return jsonify({
            "success": False,
            "error": "No meeting IDs configured or provided"
        }), 400

    try:
        result = current_app.zoom_meetings.add_to_multiple_meetings(
            meeting_ids=meeting_ids,
            email=email,
            first_name=first_name,
            last_name=last_name
        )

        # Log for audit trail
        audit_repo = _get_audit_repository()
        audit_repo.log_event(
            action="zoom_meeting_registration",
            target_id=intern_id,
            target_name=f"{first_name} {last_name}".strip(),
            actor_user_id="n8n_workflow",
            actor_name="n8n Onboarding Workflow",
            details=json.dumps({
                "email": email,
                "meeting_ids": meeting_ids,
                "success_count": len(result.get("meetings", [])),
                "error_count": len(result.get("errors", []))
            })
        )

        current_app.logger.info(
            f"[{g.request_id}] Meeting registration: {email} -> "
            f"{len(result.get('meetings', []))} success, {len(result.get('errors', []))} errors"
        )

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(
            f"[{g.request_id}] Meeting registration error: {e}",
            exc_info=True
        )
        return jsonify({
            "success": False,
            "error": f"Registration failed: {str(e)}"
        }), 500
