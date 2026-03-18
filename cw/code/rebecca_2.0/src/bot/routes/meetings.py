"""
Meeting and Recall.ai endpoints.

Handles meeting join/leave, transcription, and meeting notes.
"""

import time
import uuid
from flask import Blueprint, request, jsonify, current_app, g

from ..config import get_config
from ..middleware import require_api_auth, verify_recall_webhook

meetings_bp = Blueprint("meetings", __name__)
_config = get_config()

def _check_meeting_rate_limit(user_id: str) -> bool:
    """Check if user can join another meeting using RateLimitService."""
    if hasattr(current_app, 'rate_limit_service') and current_app.rate_limit_service:
        rate_limit = _config.rate_limit.meeting_joins_per_hour
        return current_app.rate_limit_service.check_meeting_limit(user_id, rate_limit)

    # Fallback if service not available
    return True


def _validate_meeting_url(url: str) -> bool:
    """Validate that URL is from a known meeting provider."""
    valid_domains = [
        "zoom.us", "zoom.com",
        "teams.microsoft.com", "teams.live.com",
        "meet.google.com",
    ]
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return any(domain in parsed.netloc.lower() for domain in valid_domains)
    except Exception:
        return False


@meetings_bp.route("/api/meeting/join", methods=["POST"])
@require_api_auth
def join_meeting():
    """
    Request bot to join a meeting.

    JSON body:
        meeting_url: URL of the meeting to join (required)
        bot_name: Custom bot name (optional)
        user_id: User requesting the join (for rate limiting)
        enable_voice: Enable voice responses via Output Media (optional, default: true if configured)
    """
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    data = request.json or {}
    meeting_url = data.get("meeting_url", "").strip()
    bot_name = data.get("bot_name") or current_app.config.get("RECALL_BOT_NAME", "QA Bot")
    # Support both 'user_id' and 'requested_by' for backward compatibility
    user_id = data.get("user_id") or data.get("requested_by", "unknown")
    enable_voice = data.get("enable_voice", True)

    if not meeting_url:
        return jsonify({"error": "meeting_url is required"}), 400

    # Validate URL domain
    if not _validate_meeting_url(meeting_url):
        return jsonify({"error": "Invalid meeting URL. Must be Zoom, Teams, or Google Meet."}), 400

    # Rate limit check
    if not _check_meeting_rate_limit(user_id):
        return jsonify({"error": "Meeting join rate limit exceeded. Try again later."}), 429

    # Build Output Media URL if voice is enabled
    # Note: We use meeting_id (not bot_id) in the URL since we don't have bot_id yet
    # The avatar page will use meeting_id for WebSocket routing, and we'll map it to bot_id
    output_media_url = None
    variant = None

    # Pre-generate meeting_id for Output Media URL (if needed)
    pre_meeting_id = None

    if enable_voice and current_app.config.get("VOICE_ENABLED"):
        # Use public URL for avatar page (must be accessible to Recall.ai)
        public_url = current_app.config.get("PUBLIC_URL")
        if public_url:
            # Generate meeting_id early so we can use it in the URL
            pre_meeting_id = str(uuid.uuid4())[:12]
            # Include meeting_id in URL - will be mapped to bot_id after creation
            output_media_url = f"{public_url}/avatar/page?meeting_id={pre_meeting_id}"
            variant = "web_gpu"  # Required for canvas video rendering
        else:
            # Council fix: warn when voice enabled but PUBLIC_URL missing
            current_app.logger.warning(
                "VOICE_ENABLED but PUBLIC_URL not set - Output Media disabled"
            )

    try:
        # Join via meeting handler (handles meeting record creation internally)
        # Pass pre_meeting_id so handler uses our ID instead of generating new one
        result = current_app.meeting_handler.join_meeting(
            meeting_url=meeting_url,
            requested_by=user_id,
            bot_name=bot_name,
            output_media_url=output_media_url,
            variant=variant
        )

        # Register bot_id mapping for WebSocket routing
        if result.get("bot_id") and output_media_url and pre_meeting_id:
            # Map pre_meeting_id -> bot_id for WebSocket manager
            # IMPORTANT: Use pre_meeting_id because that's what's in the Output Media URL
            # The avatar page connects with this ID, so we must map it to the bot_id
            from ...avatar.websocket_manager import get_avatar_ws_manager
            manager = get_avatar_ws_manager()
            manager.add_id_mapping(
                meeting_id=pre_meeting_id,  # The ID in the avatar page URL
                bot_id=result["bot_id"]
            )
            # Also update meeting handler's audio_bot_id_map for voice pipeline routing
            # This ensures voice responses route to the correct WebSocket connection
            if current_app.meeting_handler:
                current_app.meeting_handler._audio_bot_id_map[result["bot_id"]] = pre_meeting_id
                current_app.logger.debug(
                    f"Audio bot ID mapped: {result['bot_id'][:8]}... -> {pre_meeting_id}"
                )
            result["output_media_url"] = output_media_url
            result["voice_enabled"] = True
            current_app.logger.info(
                f"Output Media configured: url_meeting_id={pre_meeting_id}, "
                f"bot_id={result['bot_id']}"
            )

        if result.get("status") == "error":
            return jsonify({"error": result.get("error", "Failed to join meeting")}), 400

        current_app.logger.info(f"[{g.request_id}] Bot joining meeting: {result.get('meeting_id')}")
        return jsonify({
            "status": "joining",
            "meeting_id": result.get("meeting_id"),
            "bot_id": result.get("bot_id"),
        }), 201

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Join meeting error: {e}", exc_info=True)
        return jsonify({"error": f"Failed to join meeting: {str(e)}"}), 500


@meetings_bp.route("/api/meeting/<meeting_id>", methods=["GET"])
@require_api_auth
def get_meeting(meeting_id: str):
    """Get meeting details by ID."""
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    try:
        meeting = current_app.meeting_handler.get_meeting_status(meeting_id)
        if meeting:
            return jsonify(meeting)
        return jsonify({"error": "Meeting not found"}), 404
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Get meeting error: {e}", exc_info=True)
        return jsonify({"error": "Failed to get meeting"}), 500


@meetings_bp.route("/api/meeting/<meeting_id>/leave", methods=["POST"])
@require_api_auth
def leave_meeting(meeting_id: str):
    """Request bot to leave a meeting."""
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    try:
        current_app.meeting_handler.leave_meeting(meeting_id)
        current_app.logger.info(f"[{g.request_id}] Bot leaving meeting: {meeting_id}")
        return jsonify({"status": "left", "meeting_id": meeting_id})
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Leave meeting error: {e}", exc_info=True)
        return jsonify({"error": f"Failed to leave meeting: {str(e)}"}), 500


@meetings_bp.route("/api/meeting/<meeting_id>/transcript", methods=["GET"])
@require_api_auth
def get_meeting_transcript(meeting_id: str):
    """Get the transcript for a meeting."""
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    try:
        transcript = current_app.meeting_handler.get_transcript(meeting_id)
        if transcript:
            return jsonify(transcript)
        return jsonify({"error": "Transcript not found"}), 404
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Get transcript error: {e}", exc_info=True)
        return jsonify({"error": "Failed to get transcript"}), 500


@meetings_bp.route("/api/meeting/<meeting_id>/notes", methods=["GET"])
@require_api_auth
def get_meeting_notes_endpoint(meeting_id: str):
    """Get AI-generated meeting notes."""
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    try:
        notes = current_app.meeting_handler.get_meeting_notes(meeting_id)
        if notes:
            return jsonify({"meeting_id": meeting_id, "notes": notes})
        return jsonify({"error": "No transcript available or notes could not be generated"}), 404
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Get meeting notes error: {e}", exc_info=True)
        return jsonify({"error": "Failed to generate notes"}), 500


@meetings_bp.route("/api/meetings", methods=["GET"])
@require_api_auth
def list_meetings():
    """List meetings with optional filters."""
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    status = request.args.get("status")
    limit = request.args.get("limit", 20, type=int)

    try:
        # Get all meetings from meeting handler
        meetings = current_app.meeting_handler.list_meetings(
            status=status,
            limit=min(limit, 100)
        )
        return jsonify({"meetings": meetings, "count": len(meetings)})
    except AttributeError:
        # Fallback if list_meetings doesn't exist
        return jsonify({"meetings": [], "count": 0})
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] List meetings error: {e}", exc_info=True)
        return jsonify({"error": "Failed to list meetings"}), 500


@meetings_bp.route("/meeting/transcription", methods=["POST"])
def meeting_transcription_webhook():
    """Receive real-time transcription from Recall.ai."""
    # Verify webhook signature - reject unauthorized requests
    if not verify_recall_webhook():
        return jsonify({"error": "Unauthorized"}), 401

    import json

    data = request.json or {}
    event = data.get('event', 'unknown')
    current_app.logger.info(f"[{g.request_id}] Transcription webhook received: {event}")

    # Debug: log full payload structure (truncated for readability)
    try:
        payload_str = json.dumps(data, indent=2, default=str)
        if len(payload_str) > 2000:
            payload_str = payload_str[:2000] + "... (truncated)"
        current_app.logger.debug(f"[{g.request_id}] Full webhook payload:\n{payload_str}")
    except Exception:
        pass

    # Check for bot_id in headers (Recall.ai may send it there)
    bot_id = request.headers.get('X-Recall-Bot-Id') or request.headers.get('X-Bot-Id')
    if bot_id:
        data['bot_id'] = bot_id
        current_app.logger.debug(f"[{g.request_id}] Bot ID from header: {bot_id}")

    try:
        if current_app.meeting_handler:
            # Debug: check voice pipeline status
            app_has_pipeline = hasattr(current_app, 'voice_pipeline') and current_app.voice_pipeline is not None
            handler_has_pipeline = current_app.meeting_handler.voice_pipeline is not None
            current_app.logger.debug(f"[{g.request_id}] Voice status: app={app_has_pipeline}, handler={handler_has_pipeline}")

            # Ensure voice_pipeline is wired (fixes Flask debug reloader issue)
            if current_app.voice_pipeline and not current_app.meeting_handler.voice_pipeline:
                current_app.meeting_handler.voice_pipeline = current_app.voice_pipeline
                current_app.logger.info(f"[{g.request_id}] Voice pipeline wired on-demand")
            current_app.meeting_handler.handle_transcription(data)
        return jsonify({"status": "received"})
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Transcription webhook error: {e}", exc_info=True)
        return jsonify({"error": "Failed to process transcription"}), 500


@meetings_bp.route("/meeting/status", methods=["POST"])
def meeting_status_webhook():
    """
    Receive bot status updates from Recall.ai.

    Handles various Recall.ai webhook formats:
    - {data: {bot_id, status, ...}}
    - {data: {bot: {id}, data: {code, ...}}, event: "..."}
    - {bot_id, status, ...}
    """
    # Verify webhook signature - reject unauthorized requests
    if not verify_recall_webhook():
        return jsonify({"error": "Unauthorized"}), 401

    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    payload = request.json or {}

    # Extract bot_id from various formats
    bot_id = None
    status = None

    # Format 1: {data: {bot_id, status}}
    if "data" in payload:
        data = payload.get("data", {})

        # Check for bot_id directly
        bot_id = data.get("bot_id")

        # Format 2: {data: {bot: {id}}} (Recall.ai webhook format)
        if not bot_id and "bot" in data:
            bot_id = data.get("bot", {}).get("id")

        # Get status from various locations
        status = data.get("status")
        if not status and "data" in data:
            # Nested data format: {data: {data: {code}}}
            status = data.get("data", {}).get("code")
    else:
        # Format 3: Direct {bot_id, status}
        bot_id = payload.get("bot_id")
        status = payload.get("status")

    # Get event type for logging
    event_type = payload.get("event", "unknown")

    # Accept any webhook with a bot_id (permissive handling)
    if not bot_id:
        # Log but don't error - some webhooks may not have bot_id
        current_app.logger.debug(f"[{g.request_id}] Status webhook without bot_id: {event_type}")
        return jsonify({"status": "acknowledged", "note": "no bot_id"})

    # Default status if not found
    if not status:
        status = event_type or "update"

    try:
        current_app.meeting_handler.handle_status_update(bot_id, status, payload)
        current_app.logger.debug(f"[{g.request_id}] Meeting status: {bot_id} -> {status} ({event_type})")
        return jsonify({"status": "acknowledged"})
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Status webhook error: {e}", exc_info=True)
        return jsonify({"error": "Failed to update status"}), 500


@meetings_bp.route("/api/meetings/cleanup", methods=["POST"])
@require_api_auth
def cleanup_meetings():
    """Clean up stale and old meetings."""
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    try:
        stale_minutes = _config.meeting.cleanup_stale_minutes
        old_days = _config.meeting.cleanup_old_days

        stale_count = current_app.meeting_handler.cleanup_abandoned(stale_minutes)
        old_count = current_app.meeting_handler.cleanup_completed(old_days)

        current_app.logger.info(
            f"[{g.request_id}] Cleaned up {stale_count} stale, {old_count} old meetings"
        )
        return jsonify({
            "status": "cleaned",
            "abandoned": stale_count,
            "deleted": old_count
        })
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Cleanup error: {e}", exc_info=True)
        return jsonify({"error": "Failed to cleanup"}), 500


@meetings_bp.route("/api/meeting/<meeting_id>/search", methods=["GET"])
@require_api_auth
def search_meeting_transcript(meeting_id: str):
    """Search within a meeting's transcript."""
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "q (query) parameter is required"}), 400

    try:
        # Get transcript and search within it
        transcript = current_app.meeting_handler.get_transcript(meeting_id)
        if not transcript:
            return jsonify({
                "meeting_id": meeting_id,
                "query": query,
                "results": [],
                "count": 0
            })

        # Simple search within transcript segments
        results = []
        segments = transcript.get("segments", [])
        for seg in segments:
            text = seg.get("text", "")
            if query.lower() in text.lower():
                results.append(seg)

        return jsonify({
            "meeting_id": meeting_id,
            "query": query,
            "results": results,
            "count": len(results)
        })
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Search transcript error: {e}", exc_info=True)
        return jsonify({"error": "Failed to search"}), 500


@meetings_bp.route("/api/meeting/<meeting_id>/speakers", methods=["GET"])
@require_api_auth
def get_meeting_speakers(meeting_id: str):
    """Get list of speakers in a meeting."""
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    try:
        # Get transcript and extract unique speakers
        transcript = current_app.meeting_handler.get_transcript(meeting_id)
        if not transcript:
            return jsonify({
                "meeting_id": meeting_id,
                "speakers": [],
                "count": 0
            })

        # Extract unique speakers from segments
        speakers = set()
        for seg in transcript.get("segments", []):
            speaker = seg.get("speaker")
            if speaker:
                speakers.add(speaker)

        return jsonify({
            "meeting_id": meeting_id,
            "speakers": list(speakers),
            "count": len(speakers)
        })
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Get speakers error: {e}", exc_info=True)
        return jsonify({"error": "Failed to get speakers"}), 500
