"""
Flask webhook handler for QA Bot.

Receives messages from Zoom Team Chat and responds with
GitHub issue data, intern status, and QA information.

Refactored to use modular structure:
- Component initialization: bootstrap.py
- Helper functions: utils/ module
- Query handlers: handlers.py
- This file serves as thin orchestrator with backwards compatibility wrappers
"""
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from typing import Optional
from flask import Flask, request, jsonify, g
from dotenv import load_dotenv

from .config import get_config, BOT_MENTIONS
from .routes import register_all_blueprints
from .middleware import register_all_middleware
from .bootstrap import (
    bootstrap_all,
    store_components_on_app,
    _load_environment_config,
    _validate_production_config,
    _init_rate_limit_table,
)
from .handlers import (
    process_query as _process_query,
    process_query_with_brain as _process_query_with_brain,
    process_query_legacy as _process_query_legacy,
    handle_onboarding_request as _handle_onboarding_request,
    handle_offboarding_request as _handle_offboarding_request,
    handle_intern_status_request as _handle_intern_status_request,
    handle_meeting_join_request as _handle_meeting_join_request,
    handle_weekly_report_request as _handle_weekly_report_request,
)
from .utils import (
    sanitize_input,
    verify_zoom_request,
    create_zoom_challenge_response,
    verify_recall_webhook_signature,
    check_rate_limit_db,
    check_chat_rate_limit,
    check_meeting_rate_limit,
    get_repo_stats,
    format_repo_info,
)


# Load config for module-level constants
_config = get_config()

# Message deduplication cache (message_id -> timestamp)
# Uses OrderedDict for FIFO eviction when max size is reached
# Thread-safe: Protected by _dedup_cache_lock for concurrent access
_MAX_DEDUP_CACHE_SIZE = 10_000
_message_dedup_cache: OrderedDict[str, float] = OrderedDict()
_dedup_cache_lock = threading.Lock()


def _is_duplicate_message(message_id: str) -> bool:
    """
    Check if a message has already been processed.

    Uses bounded in-memory cache with TTL to prevent duplicate processing
    when Zoom sends the same webhook multiple times.

    Thread safety: Protected by _dedup_cache_lock for multi-threaded WSGI servers.
    Memory safety: Cache is bounded to _MAX_DEDUP_CACHE_SIZE entries.
    Uses FIFO eviction (oldest entries removed first) when limit reached.
    """
    current_time = time.time()
    dedup_ttl = _config.dedup.ttl_seconds

    with _dedup_cache_lock:
        # Evict if at max size (FIFO - oldest first)
        while len(_message_dedup_cache) >= _MAX_DEDUP_CACHE_SIZE:
            _message_dedup_cache.popitem(last=False)

        # Clean expired entries (batch limit for performance)
        keys_to_delete = []
        for k, v in _message_dedup_cache.items():
            if current_time - v > dedup_ttl:
                keys_to_delete.append(k)
            if len(keys_to_delete) >= 100:  # Batch cleanup limit
                break
        for k in keys_to_delete:
            del _message_dedup_cache[k]

        # Check if already processed
        if message_id in _message_dedup_cache:
            return True

        # Mark as processed
        _message_dedup_cache[message_id] = current_time
        return False


def create_app(config: dict = None) -> Flask:
    """
    Create and configure the Flask application.

    Phase 3 refactoring: Component initialization delegated to bootstrap.py.
    This function now serves as a thin orchestrator.

    Args:
        config: Optional configuration overrides

    Returns:
        Configured Flask application
    """
    from ..utils import setup_logging
    from .database import init_db, run_migrations

    # Load environment variables
    load_dotenv()

    app = Flask(__name__)

    # Add unique ID to track app instances
    app.instance_id = str(uuid.uuid4())[:8]
    print(f"Created Flask app with instance_id={app.instance_id}")

    # Apply configuration overrides
    config = config or {}
    app.config.update(config)

    # Load environment config
    _load_environment_config(app)

    # Print debug info for voice config
    raw_voice = os.getenv("VOICE_ENABLED", "false")
    print(f"VOICE_ENABLED config: raw='{raw_voice}', bool={app.config.get('VOICE_ENABLED')}, set to={app.config['VOICE_ENABLED']}")

    # Set up logging
    log_level = logging.DEBUG if app.config.get("TESTING") or app.debug else logging.INFO
    logger = setup_logging(
        log_file="qa_bot.log",
        log_dir="logs",
        level=log_level
    )
    app.logger = logger

    # Validate production configuration
    config_issues = _validate_production_config(app, logger)
    if config_issues:
        logger.info(f"Found {len(config_issues)} configuration issues to review")

    # Initialize database
    db_path = app.config["DB_PATH"]
    init_db(db_path)
    run_migrations(db_path)
    _init_rate_limit_table(db_path)

    # Create voice query handler factory for bootstrap
    def create_voice_query_handler(app_instance, qa_brain):
        """Factory to create voice query handler with access to app context."""
        def voice_query_handler(text: str, conversation_history: list = None) -> str:
            text_response = _process_query(
                app=app_instance,
                text=text,
                user_id="voice",
                user_name="Voice User",
                channel_id="",
                request_id=f"voice-{int(time.time() * 1000)}",
                conversation_history=conversation_history
            )

            if qa_brain:
                try:
                    voice_response = qa_brain.generate_voice_response(
                        data=text_response,
                        user_query=text
                    )
                    logger.debug(f"Voice response converted: {voice_response[:100]}...")
                    return voice_response
                except Exception as e:
                    logger.warning(f"Voice formatting failed: {e}, using text response")

            return text_response
        return voice_query_handler

    # Bootstrap all components using phased initialization
    bootstrap_result = bootstrap_all(app, query_handler_factory=create_voice_query_handler)

    # Store components on app for backwards compatibility
    store_components_on_app(app, bootstrap_result)

    # Debug: verify voice pipeline is stored
    logger.debug(f"App attributes set: voice_pipeline={app.voice_pipeline is not None}, meeting_handler={app.meeting_handler is not None}")

    # Register routes and handlers
    register_routes(app)
    register_error_handlers(app)

    # Pre-warm cache in background to avoid first-request delay
    if app.issue_cache and not app.config.get("TESTING"):
        import threading

        def prewarm_cache():
            try:
                logger.info("Pre-warming issue cache in background...")
                app.issue_cache.get_issues()
                logger.info("Issue cache pre-warmed successfully")
            except Exception as e:
                logger.warning(f"Cache pre-warm failed (will retry on first request): {e}")

        prewarm_thread = threading.Thread(target=prewarm_cache, daemon=True)
        prewarm_thread.start()

    # Database connection management
    @app.teardown_appcontext
    def close_db(error):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    return app


def register_error_handlers(app: Flask) -> None:
    """Register error handlers for the app."""

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Handle uncaught exceptions."""
        request_id = getattr(g, 'request_id', 'unknown')
        app.logger.error(f"[{request_id}] Unhandled exception: {e}", exc_info=True)
        return jsonify({
            "error": "An internal error occurred",
            "request_id": request_id
        }), 500


def register_routes(app: Flask) -> None:
    """Register all routes on the Flask app using blueprints."""

    @app.before_request
    def before_request():
        """Add request ID and timing to each request."""
        g.request_id = str(uuid.uuid4())[:8]
        g.start_time = time.time()

    @app.after_request
    def after_request(response):
        """Log request completion."""
        if hasattr(g, 'start_time'):
            elapsed = (time.time() - g.start_time) * 1000
            app.logger.debug(
                f"[{g.request_id}] {request.method} {request.path} "
                f"-> {response.status_code} ({elapsed:.0f}ms)"
            )
        return response

    # Register all blueprints
    register_all_blueprints(app)

    # Register security middleware (HSTS, security headers, HTTPS enforcement)
    register_all_middleware(app)


# ============================================================
# Backwards Compatibility Wrappers
# ============================================================
#
# Phase 3 Refactoring Complete:
# - Utils functions: src/bot/utils/ (sanitize_input, verify_*, check_*, formatters)
# - Handler functions: src/bot/handlers.py (process_query, handle_* requests)
# - Bootstrap functions: src/bot/bootstrap.py (component initialization)
#
# The wrappers below maintain backwards compatibility with existing tests.
# New code should import from the appropriate module directly.
#
# Note: Route definitions are in src/bot/routes/
# See: health.py, zoom.py, interns.py, workflows.py, meetings.py, voice.py, avatar.py


# Note: Handler functions (_process_query, _handle_*_request, etc.) are now
# imported from handlers.py at the top of this file. The imports use aliases
# to maintain the underscore-prefixed names for backwards compatibility.
#
# The following wrapper functions maintain compatibility with baseline tests
# that directly test app.py functions. New code should use the imported functions.


def _handle_zoom_challenge(app: Flask, data: dict) -> tuple:
    """Wrapper for backwards compatibility. Use create_zoom_challenge_response from utils."""
    return create_zoom_challenge_response(app, data, g.request_id)


def _sanitize_input(text: str, max_length: int = None) -> str:
    """Wrapper for backwards compatibility. Use sanitize_input from utils."""
    return sanitize_input(text, max_length)


def _verify_zoom_request(app: Flask, request_obj, data: dict, raw_body: str = None) -> bool:
    """Wrapper for backwards compatibility. Use verify_zoom_request from utils."""
    return verify_zoom_request(app, request_obj, data, raw_body)


def _check_rate_limit_db(app: Flask, user_id: str) -> bool:
    """Wrapper for backwards compatibility. Use check_rate_limit_db from utils."""
    return check_rate_limit_db(app, user_id)


def _check_meeting_rate_limit(app: Flask, user_id: str) -> bool:
    """Wrapper for backwards compatibility. Use check_meeting_rate_limit from utils."""
    return check_meeting_rate_limit(app, user_id)


def _verify_recall_webhook_signature(app: Flask, request_obj) -> bool:
    """Wrapper for backwards compatibility. Use verify_recall_webhook_signature from utils."""
    return verify_recall_webhook_signature(app, request_obj)


def _get_repo_stats(issues: list) -> dict:
    """Wrapper for backwards compatibility. Use get_repo_stats from utils."""
    return get_repo_stats(issues)


def _format_repo_info(repo_name: str, stats: dict, recent_issues: list) -> str:
    """Wrapper for backwards compatibility. Use format_repo_info from utils."""
    return format_repo_info(repo_name, stats, recent_issues)


# Application factory - don't create at import time
app: Optional[Flask] = None


def get_app() -> Flask:
    """Get or create the Flask application."""
    global app
    if app is None:
        app = create_app()
    return app


if __name__ == "__main__":
    # Development server
    application = create_app()
    port = int(os.getenv("PORT", "5000"))
    application.run(host="0.0.0.0", port=port, debug=True)
