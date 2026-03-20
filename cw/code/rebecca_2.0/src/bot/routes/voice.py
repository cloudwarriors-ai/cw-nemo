"""
Voice integration endpoints.

Handles TTS, voice queries, and real-time voice interaction.
"""

import base64
from flask import Blueprint, request, jsonify, current_app, g

voice_bp = Blueprint("voice", __name__)


def _verify_recall_webhook_signature() -> bool:
    """
    Verify Recall.ai webhook signature using HMAC.

    Returns True if signature valid or no secret configured.
    """
    import hashlib
    import hmac

    secret = current_app.config.get("RECALL_TRANSCRIPTION_SECRET")
    if not secret:
        return True  # No secret configured, skip verification

    signature = request.headers.get("X-Recall-Signature")
    if not signature:
        # Fall back to simple secret header check
        simple_secret = request.headers.get("X-Transcription-Secret")
        return simple_secret == secret

    # Verify HMAC signature
    try:
        expected = hmac.new(
            secret.encode(),
            request.get_data(),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)
    except Exception:
        return False


@voice_bp.route("/api/voice/status", methods=["GET"])
def voice_status():
    """Get voice pipeline status."""
    if not current_app.voice_pipeline:
        return jsonify({
            "enabled": False,
            "reason": "Voice not configured"
        })

    stats = current_app.voice_pipeline.get_latency_stats()
    return jsonify({
        "enabled": True,
        "latency_stats": stats,
        "interactions": len(current_app.voice_pipeline.interaction_history)
    })


@voice_bp.route("/api/voice/tts", methods=["POST"])
def voice_tts():
    """
    Generate speech from text (TTS endpoint).

    JSON body:
        text: Text to synthesize (required)
        voice_id: Optional voice ID

    Returns audio as base64 encoded data.
    """
    if not current_app.voice_pipeline:
        return jsonify({"error": "Voice not configured"}), 503

    data = request.json or {}
    text = data.get("text", "")

    if not text:
        return jsonify({"error": "text is required"}), 400

    try:
        tts_result = current_app.voice_pipeline.tts_client.synthesize(text)

        return jsonify({
            "audio_data": base64.b64encode(tts_result.audio_data).decode("utf-8"),
            "format": tts_result.audio_format,
            "sample_rate": tts_result.sample_rate,
            "duration_ms": tts_result.duration_ms,
            "processing_time_ms": tts_result.processing_time_ms
        })

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] TTS error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@voice_bp.route("/api/voice/query", methods=["POST"])
def voice_query():
    """
    Process a text query and return audio response.

    JSON body:
        text: Query text (required)

    Returns audio response.
    """
    if not current_app.voice_pipeline:
        return jsonify({"error": "Voice not configured"}), 503

    data = request.json or {}
    text = data.get("text", "")

    if not text:
        return jsonify({"error": "text is required"}), 400

    try:
        audio_data = current_app.voice_pipeline.process_text_query(text)

        if audio_data:
            return jsonify({
                "audio_data": base64.b64encode(audio_data).decode("utf-8"),
                "format": current_app.voice_pipeline.tts_client.output_format
                    if hasattr(current_app.voice_pipeline.tts_client, 'output_format')
                    else "mp3"
            })
        else:
            return jsonify({"error": "Failed to generate response"}), 500

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Voice query error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@voice_bp.route("/voice/audio", methods=["POST"])
def voice_audio_webhook():
    """
    Receive real-time audio webhooks from Recall.ai for voice processing.

    Requires authentication via X-Transcription-Secret header.
    """
    if not current_app.voice_webhook_handler:
        return jsonify({"error": "Voice not configured"}), 503

    # Verify webhook authentication
    if not _verify_recall_webhook_signature():
        current_app.logger.warning(f"[{g.request_id}] Unauthorized voice audio webhook")
        return jsonify({"error": "unauthorized"}), 401

    data = request.json or {}

    try:
        result = current_app.voice_webhook_handler.handle_webhook(data)
        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Voice audio webhook error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@voice_bp.route("/api/voice/start/<meeting_id>", methods=["POST"])
def start_voice_for_meeting(meeting_id: str):
    """
    Start voice interaction for a meeting.

    Associates voice pipeline with a meeting's bot for bidirectional audio.
    Validates meeting is in active state before starting.
    """
    if not current_app.voice_pipeline or not current_app.meeting_handler:
        return jsonify({"error": "Voice or meeting not configured"}), 503

    try:
        # Get meeting info
        meeting = current_app.meeting_handler.get_meeting_status(meeting_id)
        if not meeting:
            return jsonify({"error": "Meeting not found"}), 404

        # Validate meeting is in active state
        active_states = ("in_call", "recording")
        meeting_status = meeting.get("status")
        if meeting_status not in active_states:
            current_app.logger.warning(
                f"[{g.request_id}] Cannot start voice for meeting {meeting_id} "
                f"in state '{meeting_status}'"
            )
            return jsonify({
                "error": f"Meeting not in active state. Current state: {meeting_status}",
                "valid_states": list(active_states)
            }), 400

        # Update pipeline with bot ID for audio output
        current_app.voice_pipeline.recall_bot_id = meeting.get("bot_id")
        current_app.voice_pipeline.recall_api_key = current_app.config.get("RECALL_API_KEY")

        # Start pipeline
        current_app.voice_pipeline.start()

        current_app.logger.info(f"[{g.request_id}] Voice started for meeting {meeting_id}")
        return jsonify({
            "status": "started",
            "meeting_id": meeting_id,
            "bot_id": meeting.get("bot_id")
        })

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Start voice error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@voice_bp.route("/api/voice/stop", methods=["POST"])
def stop_voice():
    """Stop voice interaction."""
    if not current_app.voice_pipeline:
        return jsonify({"error": "Voice not configured"}), 503

    try:
        current_app.voice_pipeline.stop()
        return jsonify({"status": "stopped"})

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Stop voice error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
