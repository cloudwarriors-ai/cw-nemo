"""
Avatar integration endpoints.

Handles avatar sessions, state management, and webpage serving for Recall.ai.
Includes WebSocket support for real-time audio streaming to avatar webpage.
"""
import json
import logging
import os
import time

from flask import Blueprint, request, jsonify, current_app, g, send_from_directory

# WebSocket support
try:
    from flask_sock import Sock
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    Sock = None

from ...avatar.websocket_manager import get_avatar_ws_manager

avatar_bp = Blueprint("avatar", __name__)

# Static files directory for avatar webpage
AVATAR_STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "avatar",
    "static"
)

# Logger
_logger = logging.getLogger("qa_agent")


def init_avatar_websocket(app):
    """
    Initialize WebSocket support for avatar audio streaming.

    Must be called during app initialization after blueprints are registered.

    Args:
        app: Flask application instance

    Returns:
        Sock instance or None if WebSocket not available
    """
    if not WEBSOCKET_AVAILABLE:
        _logger.warning("flask-sock not installed, avatar WebSocket disabled")
        return None

    sock = Sock(app)

    @sock.route("/ws/avatar/<bot_id>")
    def avatar_websocket(ws, bot_id: str):
        """
        WebSocket endpoint for avatar audio streaming.

        The avatar webpage connects here to receive real-time audio
        that it plays through the browser's Web Audio API.

        Args:
            ws: WebSocket connection
            bot_id: Bot ID for routing audio
        """
        import time
        import threading

        manager = get_avatar_ws_manager(_logger)

        _logger.info(f"Avatar WebSocket connection: bot_id={bot_id}")

        # Register this connection
        manager.register(bot_id, ws)

        # Keepalive state
        connection_alive = True
        last_pong = time.time()
        KEEPALIVE_INTERVAL = 15  # Send ping every 15 seconds
        KEEPALIVE_TIMEOUT = 45  # Consider dead if no pong in 45 seconds

        def send_keepalive():
            """Background thread to send periodic pings."""
            nonlocal connection_alive
            while connection_alive:
                try:
                    time.sleep(KEEPALIVE_INTERVAL)
                    if not connection_alive:
                        break
                    # Send ping
                    ws.send(json.dumps({"type": "ping", "ts": time.time()}))
                except Exception as e:
                    _logger.debug(f"Keepalive send failed for {bot_id}: {e}")
                    connection_alive = False
                    break

        # Start keepalive thread
        keepalive_thread = threading.Thread(target=send_keepalive, daemon=True)
        keepalive_thread.start()

        try:
            # Send welcome message
            ws.send(json.dumps({
                "type": "welcome",
                "bot_id": bot_id,
                "message": "Connected to QA Bot audio stream"
            }))

            # Send immediate ping to get client response
            ws.send(json.dumps({"type": "ping", "ts": time.time()}))

            _logger.info(f"Avatar WebSocket ready for {bot_id}, waiting for messages")

            # Keep connection alive and handle incoming messages
            while connection_alive:
                try:
                    # Receive with timeout (shorter for responsiveness)
                    message = ws.receive(timeout=10)

                    if message is None:
                        # Timeout or connection closed - check keepalive status
                        if time.time() - last_pong > KEEPALIVE_TIMEOUT:
                            _logger.warning(f"Avatar {bot_id} no response in {KEEPALIVE_TIMEOUT}s")
                            break
                        # Otherwise continue - connection still alive
                        continue

                    # Parse message
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type", "unknown")

                        if msg_type == "hello":
                            _logger.info(f"Avatar hello received from {bot_id}")
                            last_pong = time.time()

                        elif msg_type == "pong":
                            # Keepalive response - update last seen
                            last_pong = time.time()

                        else:
                            _logger.debug(f"Avatar message from {bot_id}: {msg_type}")

                    except json.JSONDecodeError:
                        _logger.warning(f"Invalid JSON from avatar {bot_id}")

                except TimeoutError:
                    # Check if connection is still alive
                    if time.time() - last_pong > KEEPALIVE_TIMEOUT:
                        _logger.warning(f"Avatar {bot_id} keepalive timeout")
                        break
                    # Continue waiting
                except Exception as recv_err:
                    # Catch unexpected receive errors
                    _logger.warning(f"Avatar {bot_id} receive error: {recv_err}")
                    if "closed" in str(recv_err).lower() or "disconnect" in str(recv_err).lower():
                        break

        except Exception as e:
            _logger.error(f"Avatar WebSocket error for {bot_id}: {e}", exc_info=True)

        finally:
            # Stop keepalive thread
            connection_alive = False
            # Unregister on disconnect
            manager.unregister(bot_id)
            _logger.info(f"Avatar WebSocket disconnected: bot_id={bot_id}")

    _logger.info("Avatar WebSocket initialized")
    return sock


def _check_meeting_rate_limit(user_id: str) -> bool:
    """
    Check if user is within meeting rate limits.

    Returns True if OK, False if rate limited.
    """
    import sqlite3
    import time

    db_path = current_app.config["DB_PATH"]
    rate_limit = current_app.config.get("MEETING_RATE_LIMIT", 5)
    now = time.time()
    hour_ago = now - 3600

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Clean old entries
        cursor.execute(
            "DELETE FROM meeting_rate_limits WHERE timestamp < ?",
            (hour_ago,)
        )

        # Count recent meeting joins
        cursor.execute(
            "SELECT COUNT(*) FROM meeting_rate_limits WHERE user_id = ? AND timestamp > ?",
            (user_id, hour_ago)
        )
        count = cursor.fetchone()[0]

        if count >= rate_limit:
            conn.close()
            return False

        # Add new entry
        cursor.execute(
            "INSERT INTO meeting_rate_limits (user_id, timestamp) VALUES (?, ?)",
            (user_id, now)
        )
        conn.commit()
        conn.close()
        return True

    except Exception as e:
        current_app.logger.error(f"Meeting rate limit check failed: {e}")
        return False  # Fail closed - deny on error for security


@avatar_bp.route("/api/avatar/livekit-token", methods=["GET"])
def get_livekit_viewer_token():
    """
    Generate a LiveKit viewer token for the avatar page.

    The avatar page (loaded by Recall.ai) uses this token to connect
    to the LiveKit room and subscribe to the agent's video track.

    Query params:
        room: LiveKit room name

    Returns:
        JSON with url, token, and room
    """
    room_name = request.args.get("room")
    if not room_name:
        return jsonify({"error": "Missing room parameter"}), 400

    # Get LiveKit manager
    try:
        from ...avatar.livekit_manager import get_livekit_manager
        livekit_manager = get_livekit_manager()
    except Exception as e:
        current_app.logger.error(f"Failed to get LiveKit manager: {e}")
        return jsonify({"error": "LiveKit not available"}), 500

    if not livekit_manager.is_configured:
        return jsonify({"error": "LiveKit not configured"}), 500

    # Generate viewer token
    token_info = livekit_manager.generate_viewer_token(room_name)
    if not token_info:
        return jsonify({"error": "Failed to generate token"}), 500

    current_app.logger.info(f"Generated LiveKit viewer token for room: {room_name}")
    return jsonify(token_info)


@avatar_bp.route("/api/avatar/status", methods=["GET"])
def avatar_status():
    """Get avatar session status."""
    if not current_app.avatar_session_manager:
        return jsonify({
            "enabled": False,
            "reason": "Avatar not configured"
        })

    return jsonify({
        "enabled": True,
        "active": current_app.avatar_session_manager.is_active,
        "state": current_app.avatar_session_manager.get_state_for_webpage(),
        "metrics": current_app.avatar_session_manager.get_metrics()
    })


@avatar_bp.route("/api/avatar/start/<meeting_id>", methods=["POST"])
def start_avatar_for_meeting(meeting_id: str):
    """
    Start avatar session for a meeting.

    Configures the bot to display an animated avatar that lip-syncs
    to voice responses.

    Requires:
        - Meeting in active state (in_call or recording)
        - Avatar enabled in configuration
        - Recall.ai bot with web_gpu variant recommended
    """
    if not current_app.avatar_session_manager:
        return jsonify({"error": "Avatar not configured"}), 503

    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration required for avatar"}), 503

    try:
        # Verify meeting exists and is active
        meeting = current_app.meeting_handler.get_meeting_status(meeting_id)
        if not meeting:
            return jsonify({"error": "Meeting not found"}), 404

        active_states = ("in_call", "recording")
        if meeting.get("status") not in active_states:
            return jsonify({
                "error": f"Meeting not in active state: {meeting.get('status')}",
                "valid_states": list(active_states)
            }), 400

        # Start avatar session
        success = current_app.avatar_session_manager.start_session(meeting_id)

        if not success:
            return jsonify({"error": "Failed to start avatar session"}), 500

        current_app.logger.info(f"[{g.request_id}] Avatar started for meeting {meeting_id}")
        return jsonify({
            "status": "started",
            "meeting_id": meeting_id,
            "state": current_app.avatar_session_manager.get_state_for_webpage()
        })

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Start avatar error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@avatar_bp.route("/api/avatar/stop", methods=["POST"])
def stop_avatar():
    """Stop the current avatar session."""
    if not current_app.avatar_session_manager:
        return jsonify({"error": "Avatar not configured"}), 503

    try:
        current_app.avatar_session_manager.stop_session()
        return jsonify({"status": "stopped"})

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Stop avatar error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@avatar_bp.route("/api/avatar/state", methods=["GET"])
def get_avatar_state():
    """Get current avatar state for webpage rendering."""
    if not current_app.avatar_session_manager:
        return jsonify({"error": "Avatar not configured"}), 503

    return jsonify(current_app.avatar_session_manager.get_state_for_webpage())


@avatar_bp.route("/avatar/page", methods=["GET"])
def serve_avatar_page():
    """
    Serve the avatar webpage for Recall.ai Output Media.

    This page is rendered by Recall.ai's browser and displayed
    as the bot's camera feed in meetings.

    Query params:
        bot_id: Bot ID for WebSocket audio routing (required for audio)
        room: LiveKit room name (for LiveKit mode)
        mode: 'livekit' or 'websocket' (default: auto-detect)
    """
    mode = request.args.get('mode', 'auto')

    # Check if LiveKit is available and configured
    livekit_available = False
    try:
        from ...avatar.livekit_manager import get_livekit_manager
        livekit_manager = get_livekit_manager()
        livekit_available = livekit_manager.is_configured
    except ImportError:
        pass

    # Auto-detect mode: prefer LiveKit if available
    if mode == 'auto':
        mode = 'livekit' if livekit_available else 'websocket'

    # Serve LiveKit-enabled page
    if mode == 'livekit' and livekit_available:
        livekit_page = os.path.join(AVATAR_STATIC_DIR, "avatar_livekit.html")
        if os.path.exists(livekit_page):
            _logger.info("Serving LiveKit avatar page")
            return send_from_directory(AVATAR_STATIC_DIR, "avatar_livekit.html")

    # Serve WebSocket-enabled avatar page (fallback)
    if os.path.exists(os.path.join(AVATAR_STATIC_DIR, "avatar.html")):
        _logger.info("Serving WebSocket avatar page")
        return send_from_directory(AVATAR_STATIC_DIR, "avatar.html")

    # Fallback: Try dynamic page from avatar session manager
    if current_app.avatar_session_manager:
        try:
            from ...avatar.avatar_session import AvatarWebpageServer
            webpage_server = AvatarWebpageServer(
                session_manager=current_app.avatar_session_manager,
                static_image_url=current_app.config.get("RECALL_BOT_IMAGE"),
                logger=current_app.logger
            )
            return webpage_server.get_webpage_html(), 200, {"Content-Type": "text/html"}
        except Exception as e:
            current_app.logger.warning(f"Failed to generate avatar page: {e}")

    # Final fallback: simple placeholder
    return """<!DOCTYPE html>
<html>
<head><title>QA Bot</title></head>
<body style="background:#1a1a2e;display:flex;align-items:center;justify-content:center;height:100vh;">
    <div style="color:white;font-size:48px;font-family:sans-serif;">QA Bot</div>
</body>
</html>"""


@avatar_bp.route("/api/avatar/bot-id", methods=["GET"])
def get_bot_id_from_meeting():
    """
    Lookup bot_id from meeting_id.

    When Output Media URL uses meeting_id, the avatar page needs to
    resolve it to the actual bot_id for WebSocket routing.

    Query params:
        meeting_id: The meeting ID from the URL
    """
    meeting_id = request.args.get('meeting_id', '')

    if not meeting_id:
        return jsonify({"error": "meeting_id is required"}), 400

    # Lookup bot_id from meeting_id mapping
    manager = get_avatar_ws_manager()
    bot_id = manager.get_bot_id(meeting_id)

    if bot_id:
        _logger.info(f"Resolved meeting_id={meeting_id} to bot_id={bot_id}")
        return jsonify({"bot_id": bot_id, "meeting_id": meeting_id})

    # If not found, return unknown (page will retry)
    _logger.warning(f"No bot_id found for meeting_id={meeting_id}")
    return jsonify({"bot_id": "unknown", "meeting_id": meeting_id, "found": False})


@avatar_bp.route("/api/avatar/livekit-token", methods=["GET"])
def get_livekit_token():
    """
    Generate a LiveKit access token for the avatar page.

    Query params:
        room: Room name (required)
        bot_id: Bot ID for tracking

    Returns:
        JSON with url and token for connecting to LiveKit
    """
    room_name = request.args.get('room')
    bot_id = request.args.get('bot_id', 'avatar-viewer')

    if not room_name:
        return jsonify({"error": "room parameter required"}), 400

    try:
        from ...avatar.livekit_manager import get_livekit_manager
        manager = get_livekit_manager()

        if not manager.is_configured:
            return jsonify({"error": "LiveKit not configured"}), 503

        # Generate token for viewer (can subscribe, cannot publish)
        token = manager.generate_token(
            room_name=room_name,
            participant_name=f"viewer-{bot_id}",
            can_publish=False,
            can_subscribe=True,
        )

        if not token:
            return jsonify({"error": "Failed to generate token"}), 500

        return jsonify({
            "url": manager.livekit_url,
            "token": token,
            "room": room_name,
        })

    except ImportError:
        return jsonify({"error": "LiveKit not available"}), 503
    except Exception as e:
        current_app.logger.error(f"LiveKit token error: {e}")
        return jsonify({"error": str(e)}), 500


@avatar_bp.route("/api/avatar/livekit/rooms", methods=["GET"])
def list_livekit_rooms():
    """List all active LiveKit rooms."""
    try:
        from ...avatar.livekit_manager import get_livekit_manager
        manager = get_livekit_manager()

        if not manager.is_configured:
            return jsonify({"error": "LiveKit not configured"}), 503

        rooms = manager.list_rooms()
        return jsonify({"rooms": rooms})

    except ImportError:
        return jsonify({"error": "LiveKit not available"}), 503


@avatar_bp.route("/api/avatar/livekit/room/<room_name>", methods=["POST"])
def create_livekit_room(room_name: str):
    """
    Create a LiveKit room for avatar session.

    JSON body:
        meeting_id: Associated meeting ID (optional)
    """
    data = request.json or {}
    meeting_id = data.get('meeting_id')

    try:
        from ...avatar.livekit_manager import get_livekit_manager
        manager = get_livekit_manager()

        if not manager.is_configured:
            return jsonify({"error": "LiveKit not configured"}), 503

        success = manager.create_room(room_name, meeting_id)
        if success:
            return jsonify({
                "status": "created",
                "room": room_name,
                "meeting_id": meeting_id,
            })
        else:
            return jsonify({"error": "Failed to create room"}), 500

    except ImportError:
        return jsonify({"error": "LiveKit not available"}), 503


@avatar_bp.route("/api/avatar/livekit/room/<room_name>", methods=["DELETE"])
def delete_livekit_room(room_name: str):
    """Delete a LiveKit room."""
    try:
        from ...avatar.livekit_manager import get_livekit_manager
        manager = get_livekit_manager()

        if not manager.is_configured:
            return jsonify({"error": "LiveKit not configured"}), 503

        success = manager.delete_room(room_name)
        return jsonify({"status": "deleted" if success else "not_found"})

    except ImportError:
        return jsonify({"error": "LiveKit not available"}), 503


@avatar_bp.route("/avatar/health", methods=["GET"])
def avatar_health():
    """Health check for avatar subsystem including WebSocket status."""
    manager = get_avatar_ws_manager(_logger)
    ws_stats = manager.get_stats()

    return jsonify({
        "status": "ok",
        "websocket_available": WEBSOCKET_AVAILABLE,
        "websocket_connections": ws_stats,
        "avatar_session_manager": current_app.avatar_session_manager is not None
    })


@avatar_bp.route("/avatar/dashboard", methods=["GET"])
def avatar_dashboard():
    """
    Connection health dashboard for monitoring WebSocket connections.

    Returns detailed health metrics for all active avatar connections:
    - Connection health status (healthy/stale/idle/unhealthy)
    - Connection age and last activity timestamps
    - Audio sent metrics (count, bytes)
    - Error counts
    - Summary statistics
    """
    manager = get_avatar_ws_manager(_logger)
    health_data = manager.get_connection_health()

    # Add voice pipeline stats if available
    voice_stats = {}
    if hasattr(current_app, 'voice_pipeline') and current_app.voice_pipeline:
        try:
            voice_stats = current_app.voice_pipeline.get_latency_stats()
        except Exception:
            pass

    return jsonify({
        "status": "ok",
        "websocket": health_data,
        "voice_pipeline": voice_stats,
        "server_time": time.time()
    })


@avatar_bp.route("/avatar/dashboard/html", methods=["GET"])
def avatar_dashboard_html():
    """
    HTML dashboard for connection monitoring.

    Provides a visual dashboard that auto-refreshes to show
    real-time connection health.
    """
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Avatar Connection Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
        }
        h1 { margin-bottom: 20px; color: #667eea; }
        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: #16213e;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }
        .stat-card .value {
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
        }
        .stat-card .label {
            font-size: 12px;
            color: #888;
            margin-top: 5px;
        }
        .connections {
            background: #16213e;
            border-radius: 10px;
            padding: 20px;
        }
        .connection {
            background: #1a1a2e;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 15px;
            align-items: center;
        }
        .health-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }
        .health-dot.healthy { background: #38ef7d; }
        .health-dot.idle { background: #f5a623; }
        .health-dot.stale { background: #f5a623; }
        .health-dot.unhealthy { background: #eb3349; }
        .bot-id { font-family: monospace; font-size: 14px; }
        .metrics { display: flex; gap: 20px; font-size: 12px; color: #888; }
        .no-connections {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        .refresh-info {
            text-align: right;
            font-size: 12px;
            color: #666;
            margin-bottom: 10px;
        }
    </style>
</head>
<body>
    <h1>Avatar Connection Dashboard</h1>
    <div class="refresh-info">Auto-refreshes every 5 seconds</div>

    <div class="summary" id="summary"></div>

    <h2 style="margin-bottom: 15px;">Active Connections</h2>
    <div class="connections" id="connections"></div>

    <script>
        // XSS protection: escape HTML entities
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function refresh() {
            try {
                const res = await fetch('/avatar/dashboard');
                const data = await res.json();

                const summary = data.websocket.summary;
                document.getElementById('summary').innerHTML = `
                    <div class="stat-card">
                        <div class="value">${summary.total_connections}</div>
                        <div class="label">Active Connections</div>
                    </div>
                    <div class="stat-card">
                        <div class="value">${summary.healthy}</div>
                        <div class="label">Healthy</div>
                    </div>
                    <div class="stat-card">
                        <div class="value">${summary.total_audio_messages}</div>
                        <div class="label">Audio Messages</div>
                    </div>
                    <div class="stat-card">
                        <div class="value">${summary.total_mb_sent.toFixed(1)}</div>
                        <div class="label">MB Sent</div>
                    </div>
                `;

                const connections = data.websocket.connections;
                if (connections.length === 0) {
                    document.getElementById('connections').innerHTML =
                        '<div class="no-connections">No active connections</div>';
                } else {
                    document.getElementById('connections').innerHTML = connections.map(c => `
                        <div class="connection">
                            <div class="health-dot ${escapeHtml(c.health)}"></div>
                            <div>
                                <div class="bot-id">${escapeHtml(c.bot_id)}</div>
                                <div class="metrics">
                                    <span>Age: ${Math.round(c.connection_age_seconds)}s</span>
                                    <span>Audio: ${c.audio_sent_count} msgs</span>
                                    <span>Sent: ${c.total_kb_sent} KB</span>
                                    <span>State: ${escapeHtml(c.last_state)}</span>
                                </div>
                            </div>
                            <div style="color: ${c.health === 'healthy' ? '#38ef7d' : '#f5a623'}">
                                ${escapeHtml(c.health.toUpperCase())}
                            </div>
                        </div>
                    `).join('');
                }
            } catch (e) {
                console.error('Dashboard refresh failed:', e);
            }
        }

        refresh();
        setInterval(refresh, 5000);
    </script>
</body>
</html>"""


@avatar_bp.route("/api/meeting/join-with-avatar", methods=["POST"])
def join_meeting_with_avatar():
    """
    Join a meeting with avatar enabled.

    This endpoint delegates to MeetingService which handles:
    1. Avatar page URL generation with unique bot IDs
    2. Recall.ai bot creation with Output Media configured
    3. WebSocket ID mapping for audio routing

    JSON body:
        meeting_url: Meeting URL (required)
        bot_name: Bot display name (optional)
        requested_by: User requesting (optional)
        mode: 'livekit' or 'websocket' (default: websocket)
    """
    # Use MeetingService if available (preferred path)
    if hasattr(current_app, 'meeting_service') and current_app.meeting_service:
        data = request.json or {}
        meeting_url = data.get("meeting_url")
        requested_by = data.get("requested_by", "api")

        if not meeting_url:
            return jsonify({"error": "meeting_url is required"}), 400

        try:
            result = current_app.meeting_service.join_meeting(
                meeting_url=meeting_url,
                requested_by=requested_by,
                bot_name=data.get("bot_name"),
                channel_id=data.get("channel_id"),
                with_avatar=True,
                avatar_mode=data.get("mode", "websocket")
            )

            if not result.success:
                return jsonify({"error": result.error or result.message}), 400

            current_app.logger.info(
                f"[{g.request_id}] Bot joining with avatar: {result.meeting_id}"
            )

            return jsonify({
                "status": "joining",
                "bot_id": result.bot_id,
                "meeting_id": result.meeting_id,
                "avatar_enabled": result.avatar_enabled,
                "avatar_mode": result.avatar_mode,
                "avatar_page_url": result.avatar_page_url,
                "livekit_room": result.livekit_room,
            }), 201

        except Exception as e:
            current_app.logger.error(
                f"[{g.request_id}] Join with avatar error: {e}", exc_info=True
            )
            return jsonify({"error": str(e)}), 500

    # Fallback if MeetingService not configured
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    return jsonify({"error": "MeetingService not configured"}), 503


@avatar_bp.route("/api/meeting/join-audio-only", methods=["POST"])
def join_meeting_audio_only():
    """
    Join a meeting with audio-only agent (no Simli avatar).

    This is useful for testing the voice pipeline without consuming Simli API calls.
    Uses OpenAI Realtime Model for STT + LLM + TTS.

    JSON body:
        meeting_url: Meeting URL (required)
        bot_name: Bot display name (optional)
        requested_by: User requesting (optional)
    """
    if not current_app.meeting_handler:
        return jsonify({"error": "Meeting integration not configured"}), 503

    data = request.json or {}
    meeting_url = data.get("meeting_url")
    requested_by = data.get("requested_by", "api")

    if not meeting_url:
        return jsonify({"error": "meeting_url is required"}), 400

    try:
        # Check if LiveKit is available
        livekit_available = False
        livekit_manager = None

        try:
            from ...avatar.livekit_manager import get_livekit_manager
            livekit_manager = get_livekit_manager()
            livekit_available = livekit_manager.is_configured
        except ImportError:
            pass

        if not livekit_available:
            return jsonify({"error": "LiveKit not configured - required for audio agent"}), 503

        # Generate a unique room/bot ID
        import hashlib
        meeting_hash = hashlib.md5(meeting_url.encode()).hexdigest()[:8]
        bot_id = f"qa-bot-audio-{meeting_hash}"
        room_name = f"audio-{bot_id}"

        # Create LiveKit room
        livekit_manager.create_room(room_name, meeting_id=meeting_hash)
        current_app.logger.info(f"Created LiveKit room for audio test: {room_name}")

        # Start audio-only agent (not the Simli avatar agent)
        import subprocess
        import sys
        import os as os_module

        agent_script = os_module.path.join(
            os_module.path.dirname(os_module.path.dirname(os_module.path.dirname(__file__))),
            "platform",
            "livekit_audio_test.py"
        )

        current_app.logger.info(f"Starting audio-only agent: {agent_script}")
        process = subprocess.Popen(
            [sys.executable, agent_script, "start"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os_module.path.dirname(os_module.path.dirname(os_module.path.dirname(os_module.path.dirname(__file__)))),
            env={**os_module.environ},
        )
        current_app.logger.info(f"Audio agent started (pid={process.pid})")

        # Dispatch agent to room after it registers
        livekit_manager._dispatch_agent_to_room(room_name)

        # Build simple avatar page URL (static image, no video)
        import os
        base_url = os.getenv("AVATAR_PAGE_BASE_URL") or os.getenv("PUBLIC_URL")
        if not base_url:
            base_url = f"https://{request.host}"
        avatar_page_url = f"{base_url}/avatar/page?mode=websocket&bot_id={bot_id}"

        # Join meeting with Output Media (static avatar image)
        result = current_app.meeting_handler.join_meeting(
            meeting_url=meeting_url,
            requested_by=requested_by,
            channel_id=data.get("channel_id"),
            bot_name=data.get("bot_name", "QA Bot (Audio)"),
            output_media_url=avatar_page_url,
            variant="web_gpu",
            audio_bot_id=bot_id,  # Pass the bot_id used in avatar page URL
        )

        if result.get("status") == "error":
            return jsonify(result), 400

        current_app.logger.info(f"[{g.request_id}] Bot joining audio-only: {result.get('meeting_id')}")
        return jsonify({
            **result,
            "avatar_enabled": False,
            "audio_only": True,
            "livekit_room": room_name,
            "agent_pid": process.pid,
        }), 201

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Join audio-only error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
