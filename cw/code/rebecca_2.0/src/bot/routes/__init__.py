"""
Route blueprints for the QA Bot.

Each blueprint handles a specific domain:
- health: Health check and debug endpoints
- zoom: Zoom webhook and chat endpoints
- interns: Intern management endpoints
- workflows: n8n workflow endpoints
- github: GitHub org management endpoints
- meetings: Meeting/Recall.ai endpoints
- voice: Voice pipeline endpoints
- avatar: Avatar endpoints
"""

from .health import health_bp
from .zoom import zoom_bp
from .interns import interns_bp
from .workflows import workflows_bp
from .github import github_bp
from .meetings import meetings_bp
from .voice import voice_bp
from .avatar import avatar_bp, init_avatar_websocket

__all__ = [
    "health_bp",
    "zoom_bp",
    "interns_bp",
    "workflows_bp",
    "github_bp",
    "meetings_bp",
    "voice_bp",
    "avatar_bp",
    "init_avatar_websocket",
]


def register_all_blueprints(app):
    """Register all blueprints with the Flask app."""
    app.register_blueprint(health_bp)
    app.register_blueprint(zoom_bp)
    app.register_blueprint(interns_bp)
    app.register_blueprint(workflows_bp)
    app.register_blueprint(github_bp)
    app.register_blueprint(meetings_bp)
    app.register_blueprint(voice_bp)
    app.register_blueprint(avatar_bp)

    # Initialize WebSocket support for avatar audio streaming
    # Must be called after blueprints are registered
    init_avatar_websocket(app)
