"""
Application bootstrap module for phased component initialization.

Extracted from app.py during Phase 3 refactoring.
Organizes service initialization into clear phases for better
maintainability and testability.
"""
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from flask import Flask
from dotenv import load_dotenv

from ..github_client import GitHubClient
from ..zoom_notifier import ZoomNotifier
from ..zoom_chatbot import ZoomChatbot
from ..zoom_meetings import ZoomMeetingsClient
from ..utils import setup_logging
from .query_parser import QueryParser
from .llm_brain import QABrain
from .cache import IssueCache
from .escalation import EscalationManager
from .response_builder import ResponseBuilder
from .database import init_db, run_migrations
from .n8n_client import N8nClient
from .config import get_config


@dataclass
class CoreComponents:
    """Phase 1: Core infrastructure components."""
    logger: logging.Logger
    db_path: str
    config: Any  # Config object


@dataclass
class GitHubComponents:
    """Phase 2: GitHub and query processing components."""
    github_client: Optional[GitHubClient] = None
    issue_cache: Optional[IssueCache] = None
    zoom_notifier: Optional[ZoomNotifier] = None
    query_parser: Optional[QueryParser] = None
    qa_brain: Optional[QABrain] = None
    escalation_manager: Optional[EscalationManager] = None
    response_builder: Optional[ResponseBuilder] = None


@dataclass
class ZoomComponents:
    """Phase 3: Zoom integration components."""
    n8n_client: Optional[N8nClient] = None
    zoom_chatbot: Optional[ZoomChatbot] = None
    zoom_meetings: Optional[ZoomMeetingsClient] = None


@dataclass
class MeetingComponents:
    """Phase 4: Recall.ai meeting components."""
    recall_client: Any = None  # RecallClient
    meeting_handler: Any = None  # MeetingHandler
    transcription_processor: Any = None  # TranscriptionProcessor


@dataclass
class VoiceAvatarComponents:
    """Phase 5: Voice pipeline and avatar components."""
    voice_pipeline: Any = None
    voice_webhook_handler: Any = None
    avatar_session_manager: Any = None


@dataclass
class ServicesComponents:
    """Phase 6: Business services layer."""
    rate_limit_service: Any = None
    auth_service: Any = None
    conversation_flow_handler: Any = None
    query_service: Any = None
    report_service: Any = None
    hygiene_service: Any = None
    feedback_service: Any = None
    channel_manager: Any = None
    workflow_orchestrator: Any = None
    meeting_service: Any = None  # MeetingService for meeting join operations
    # Repositories
    intern_repository: Any = None
    query_log_repository: Any = None
    workflow_repository: Any = None
    meeting_repository: Any = None
    conversation_flow_repository: Any = None
    audit_repository: Any = None


@dataclass
class BootstrapResult:
    """Complete bootstrap result with all components."""
    core: CoreComponents
    github: GitHubComponents
    zoom: ZoomComponents
    meeting: MeetingComponents
    voice_avatar: VoiceAvatarComponents
    services: ServicesComponents


def _init_rate_limit_table(db_path: str) -> None:
    """Initialize rate limit tables in database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_rate_limits_user
        ON rate_limits(user_id, timestamp)
    """)
    # Meeting-specific rate limits (more restrictive)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meeting_rate_limits (
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_meeting_rate_limits_user
        ON meeting_rate_limits(user_id, timestamp)
    """)
    conn.commit()
    conn.close()


def bootstrap_phase_1_core(app: Flask) -> CoreComponents:
    """
    Phase 1: Initialize core infrastructure.

    - Load environment variables
    - Configure Flask app settings
    - Set up logging
    - Initialize database

    Args:
        app: Flask application instance

    Returns:
        CoreComponents with logger, db_path, and config
    """
    # Load environment variables
    load_dotenv()

    # Read configuration from environment
    _load_environment_config(app)

    # Set up logging
    log_level = logging.DEBUG if app.config.get("TESTING") or app.debug else logging.INFO
    logger = setup_logging(
        log_file="qa_bot.log",
        log_dir="logs",
        level=log_level
    )
    app.logger = logger

    # Validate production configuration - will raise ConfigurationError for critical issues
    config_warnings = _validate_production_config(app, logger)
    if config_warnings:
        logger.info(f"Starting with {len(config_warnings)} non-critical config warnings")

    # Initialize database
    db_path = app.config["DB_PATH"]
    init_db(db_path)
    run_migrations(db_path)
    _init_rate_limit_table(db_path)

    return CoreComponents(
        logger=logger,
        db_path=db_path,
        config=get_config()
    )


def bootstrap_phase_2_github(
    app: Flask,
    logger: logging.Logger,
    db_path: str
) -> GitHubComponents:
    """
    Phase 2: Initialize GitHub and query processing components.

    - GitHub client
    - Issue cache
    - Query parser (legacy fallback)
    - QA Brain (LLM)
    - Escalation manager
    - Response builder

    Args:
        app: Flask application instance
        logger: Logger from Phase 1
        db_path: Database path from Phase 1

    Returns:
        GitHubComponents with all initialized components
    """
    result = GitHubComponents()

    github_token = app.config["GITHUB_TOKEN"]
    repos = app.config["REPOS"]

    if github_token and repos:
        result.github_client = GitHubClient(
            token=github_token,
            org=app.config["GITHUB_ORG"],
            logger=logger
        )
        result.issue_cache = IssueCache(
            github_client=result.github_client,
            repos=repos,
            db_path=db_path,
            ttl_seconds=app.config["CACHE_TTL"],
            logger=logger
        )

    result.zoom_notifier = ZoomNotifier(logger=logger)
    result.query_parser = QueryParser(logger=logger)

    # Initialize LLM Brain if configured
    openrouter_key = app.config.get("OPENROUTER_API_KEY")
    if openrouter_key:
        result.qa_brain = QABrain(
            api_key=openrouter_key,
            model=app.config.get("LLM_MODEL", "anthropic/claude-haiku-4.5"),
            repos=repos,
            logger=logger
        )
        logger.info("QA Brain initialized with LLM")
    else:
        logger.warning("No OPENROUTER_API_KEY configured - using keyword matching fallback")

    result.escalation_manager = EscalationManager(
        zoom_notifier=result.zoom_notifier,
        default_contact=app.config["ESCALATION_CONTACT"],
        db_path=db_path,
        logger=logger
    )
    result.response_builder = ResponseBuilder()

    return result


def bootstrap_phase_3_zoom(
    app: Flask,
    logger: logging.Logger,
    db_path: str
) -> ZoomComponents:
    """
    Phase 3: Initialize Zoom integration components.

    - N8n client (workflow automation)
    - Zoom chatbot
    - Zoom meetings client (S2S OAuth)

    Args:
        app: Flask application instance
        logger: Logger from Phase 1
        db_path: Database path from Phase 1

    Returns:
        ZoomComponents with all initialized components
    """
    result = ZoomComponents()

    # Initialize n8n client if configured
    n8n_webhook_url = app.config.get("N8N_WEBHOOK_URL")
    if n8n_webhook_url:
        result.n8n_client = N8nClient(
            webhook_base_url=n8n_webhook_url,
            db_path=db_path,
            logger=logger
        )
        logger.info(f"n8n client initialized: {n8n_webhook_url}")

    # Initialize Zoom Chatbot if configured
    zoom_client_id = app.config.get("ZOOM_CLIENT_ID")
    zoom_client_secret = app.config.get("ZOOM_CLIENT_SECRET")
    zoom_bot_jid = app.config.get("ZOOM_BOT_JID")
    zoom_account_id = app.config.get("ZOOM_ACCOUNT_ID")

    # S2S credentials for admin APIs
    s2s_client_id = app.config.get("ZOOM_S2S_CLIENT_ID")
    s2s_client_secret = app.config.get("ZOOM_S2S_CLIENT_SECRET")
    s2s_account_id = app.config.get("ZOOM_S2S_ACCOUNT_ID")

    if zoom_client_id and zoom_client_secret:
        result.zoom_chatbot = ZoomChatbot(
            client_id=zoom_client_id,
            client_secret=zoom_client_secret,
            bot_jid=zoom_bot_jid,
            account_id=zoom_account_id,
            s2s_client_id=s2s_client_id,
            s2s_client_secret=s2s_client_secret,
            s2s_account_id=s2s_account_id,
            logger=logger
        )
        logger.info("Zoom Chatbot initialized")

    # Initialize Zoom Meetings client (uses S2S OAuth)
    if s2s_client_id and s2s_client_secret and s2s_account_id:
        result.zoom_meetings = ZoomMeetingsClient(
            client_id=s2s_client_id,
            client_secret=s2s_client_secret,
            account_id=s2s_account_id,
            logger=logger
        )
        logger.info("Zoom Meetings client initialized (S2S OAuth)")

    return result


def bootstrap_phase_4_meetings(
    app: Flask,
    logger: logging.Logger,
    db_path: str
) -> MeetingComponents:
    """
    Phase 4: Initialize Recall.ai meeting components.

    - Recall client
    - Meeting handler
    - Transcription processor

    Args:
        app: Flask application instance
        logger: Logger from Phase 1
        db_path: Database path from Phase 1

    Returns:
        MeetingComponents with all initialized components
    """
    result = MeetingComponents()

    recall_api_key = app.config.get("RECALL_API_KEY")
    if not recall_api_key:
        return result

    from ..meeting.recall_client import RecallClient
    from ..meeting.meeting_handler import MeetingHandler
    from ..meeting.transcription import TranscriptionProcessor

    # Build transcription webhook URL
    transcription_url = None
    public_url = app.config.get("PUBLIC_URL")
    if public_url:
        transcription_url = f"{public_url.rstrip('/')}/meeting/transcription"
        logger.info(f"Transcription webhook URL: {transcription_url}")
    elif app.config.get("SERVER_NAME"):
        transcription_url = f"https://{app.config['SERVER_NAME']}/meeting/transcription"

    result.recall_client = RecallClient(
        api_key=recall_api_key,
        bot_name=app.config.get("RECALL_BOT_NAME", "QA Bot"),
        bot_image_url=app.config.get("RECALL_BOT_IMAGE"),
        transcription_webhook_url=transcription_url,
        transcription_webhook_secret=app.config.get("RECALL_TRANSCRIPTION_SECRET"),
        logger=logger
    )

    result.meeting_handler = MeetingHandler(
        recall_client=result.recall_client,
        db_path=db_path,
        bot_name=app.config.get("RECALL_BOT_NAME", "QA Bot"),
        logger=logger
    )

    result.transcription_processor = TranscriptionProcessor(
        db_path=db_path,
        logger=logger
    )

    logger.info("Recall.ai meeting handler initialized")

    return result


def bootstrap_phase_5_voice_avatar(
    app: Flask,
    logger: logging.Logger,
    query_handler: Optional[Callable[[str, list], str]] = None,
    meeting_handler: Any = None
) -> VoiceAvatarComponents:
    """
    Phase 5: Initialize voice pipeline and avatar components.

    - Voice pipeline (Whisper ASR + TTS)
    - Voice webhook handler
    - Avatar session manager (Simli)

    Args:
        app: Flask application instance
        logger: Logger from Phase 1
        query_handler: Callback function for voice queries
        meeting_handler: Meeting handler to wire voice pipeline to

    Returns:
        VoiceAvatarComponents with all initialized components
    """
    result = VoiceAvatarComponents()

    # Initialize voice pipeline if enabled
    voice_enabled = app.config.get("VOICE_ENABLED")
    has_openai_key = bool(app.config.get("OPENAI_API_KEY"))

    logger.debug(f"Voice init check: VOICE_ENABLED={voice_enabled}, has_openai_key={has_openai_key}")

    if voice_enabled and has_openai_key and query_handler:
        try:
            from ..voice.voice_pipeline import create_voice_pipeline, VoiceWebhookHandler

            result.voice_pipeline = create_voice_pipeline(
                openai_api_key=app.config["OPENAI_API_KEY"],
                cartesia_api_key=app.config.get("CARTESIA_API_KEY"),
                recall_api_key=app.config.get("RECALL_API_KEY"),
                query_handler=query_handler,
                logger=logger
            )

            result.voice_webhook_handler = VoiceWebhookHandler(
                pipeline=result.voice_pipeline,
                secret=app.config.get("RECALL_TRANSCRIPTION_SECRET"),
                logger=logger
            )

            # Wire voice pipeline to meeting handler
            if meeting_handler:
                meeting_handler.voice_pipeline = result.voice_pipeline
                logger.info("Voice pipeline wired to meeting handler")

            logger.info("Voice pipeline initialized")

        except Exception as e:
            logger.error(f"Failed to initialize voice pipeline: {e}. Voice features disabled.")

    # Initialize avatar session manager if enabled
    if app.config.get("AVATAR_ENABLED") and app.config.get("SIMLI_API_KEY"):
        try:
            from ..avatar.simli_client import SimliClient
            from ..avatar.avatar_session import AvatarSessionManager

            simli_client = SimliClient(
                api_key=app.config["SIMLI_API_KEY"],
                face_id=app.config.get("AVATAR_FACE_ID") or None,
                logger=logger
            )

            result.avatar_session_manager = AvatarSessionManager(
                simli_client=simli_client,
                logger=logger
            )

            # Wire avatar to meeting handler
            if meeting_handler:
                meeting_handler._avatar_session_manager = result.avatar_session_manager
                logger.info("Avatar session manager wired into meeting handler")

            logger.info("Avatar session manager initialized")

        except Exception as e:
            logger.error(f"Failed to initialize avatar: {e}. Avatar features disabled.")

    return result


def bootstrap_phase_6_services(
    app: Flask,
    logger: logging.Logger,
    db_path: str,
    github: GitHubComponents,
    zoom: ZoomComponents,
    meeting: MeetingComponents
) -> ServicesComponents:
    """
    Phase 6: Initialize business services layer.

    - RateLimitService
    - AuthService
    - ConversationFlowHandler
    - QueryService
    - ReportService
    - HygieneService
    - FeedbackService
    - ChannelManager
    - WorkflowOrchestrator

    Args:
        app: Flask application instance
        logger: Logger from Phase 1
        db_path: Database path from Phase 1
        github: GitHub components from Phase 2
        zoom: Zoom components from Phase 3
        meeting: Meeting components from Phase 4

    Returns:
        ServicesComponents with all initialized services
    """
    from .services import (
        RateLimitService, QueryService, AuthService, ReportService,
        HygieneService, FeedbackService, ConversationFlowHandler,
        WorkflowOrchestrator, WorkflowCapabilityHandler, MeetingService
    )
    from .channels import ChannelManager, ZoomChannelAdapter
    from .config import get_config
    from .repositories import (
        InternRepository,
        QueryLogRepository,
        WorkflowRepository,
        MeetingRepository,
        ConversationFlowRepository,
        AuditRepository,
    )

    config = get_config()
    result = ServicesComponents()

    # Initialize repositories
    result.intern_repository = InternRepository(db_path=db_path, logger=logger)
    result.query_log_repository = QueryLogRepository(db_path=db_path, logger=logger)
    result.workflow_repository = WorkflowRepository(db_path=db_path, logger=logger)
    result.meeting_repository = MeetingRepository(db_path=db_path, logger=logger)
    result.conversation_flow_repository = ConversationFlowRepository(db_path=db_path, logger=logger)
    result.audit_repository = AuditRepository(db_path=db_path, logger=logger)
    logger.info("Repositories initialized")

    # Rate limit service
    result.rate_limit_service = RateLimitService(
        db_path=db_path,
        logger=logger
    )

    # Auth service
    is_production = not (app.config.get("TESTING") or app.debug)

    result.auth_service = AuthService(
        zoom_token=app.config.get("ZOOM_BOT_TOKEN"),
        zoom_secret=app.config.get("ZOOM_BOT_SECRET"),
        recall_secret=app.config.get("RECALL_TRANSCRIPTION_SECRET"),
        n8n_secret=app.config.get("N8N_CALLBACK_SECRET"),
        api_key=app.config.get("API_KEY"),
        authorized_onboarding_users=config.authorization.authorized_onboarding_users,
        allowed_email_domains=config.authorization.allowed_email_domains,
        require_production_auth=is_production,
        logger=logger
    )

    if is_production and not app.config.get("API_KEY"):
        logger.warning("SECURITY: No API_KEY configured - API endpoints require authentication")

    # Conversation flow handler
    meeting_ids = [
        m["meeting_id"] for m in config.onboarding.recurring_meetings
    ] if config.onboarding.recurring_meetings else []

    result.conversation_flow_handler = ConversationFlowHandler(
        db_path=db_path,
        n8n_client=zoom.n8n_client,
        github_client=github.github_client,
        zoom_meetings_client=zoom.zoom_meetings,
        meeting_ids=meeting_ids,
        allowed_email_domains=config.authorization.allowed_email_domains,
        logger=logger
    )

    # Query service
    result.query_service = QueryService(
        qa_brain=github.qa_brain,
        query_parser=github.query_parser,
        issue_cache=github.issue_cache,
        escalation_manager=github.escalation_manager,
        response_builder=github.response_builder,
        conversation_flow_handler=result.conversation_flow_handler,
        logger=logger
    )

    # Report service
    if github.issue_cache:
        result.report_service = ReportService(
            issue_cache=github.issue_cache,
            logger=logger
        )
        logger.info("Report service initialized")

    # Hygiene service
    if github.issue_cache:
        result.hygiene_service = HygieneService(
            issue_cache=github.issue_cache,
            logger=logger
        )
        logger.info("Hygiene service initialized")

    # Feedback service
    result.feedback_service = FeedbackService(
        db_path=db_path,
        logger=logger
    )
    logger.info("Feedback service initialized")

    # Channel manager
    result.channel_manager = ChannelManager(logger=logger)

    # Register Zoom channel adapter
    zoom_account_id = app.config.get("ZOOM_ACCOUNT_ID")
    if zoom.zoom_chatbot and zoom_account_id:
        zoom_adapter = ZoomChannelAdapter(
            chatbot=zoom.zoom_chatbot,
            account_id=zoom_account_id,
            logger=logger
        )
        result.channel_manager.register_adapter(zoom_adapter)
        logger.info("Zoom channel adapter registered")

    # Workflow orchestrator
    result.workflow_orchestrator = WorkflowOrchestrator(
        qa_brain=github.qa_brain,
        channel_manager=result.channel_manager,
        report_service=result.report_service,
        hygiene_service=result.hygiene_service,
        feedback_service=result.feedback_service,
        n8n_client=zoom.n8n_client,
        logger=logger
    )
    logger.info("Workflow orchestrator initialized")

    # Meeting service (centralized meeting join operations)
    public_url = app.config.get("PUBLIC_URL")
    if meeting.meeting_handler:
        # Import ws_manager from avatar module if available
        ws_manager = None
        try:
            from ..avatar.websocket_manager import get_websocket_manager
            ws_manager = get_websocket_manager()
        except ImportError:
            pass

        result.meeting_service = MeetingService(
            meeting_handler=meeting.meeting_handler,
            ws_manager=ws_manager,
            public_url=public_url,
            default_bot_name=app.config.get("RECALL_BOT_NAME", "QA Bot"),
            logger=logger
        )
        logger.info("Meeting service initialized")

    # Create workflow capability handler (needs dependencies from later phases)
    workflow_capability_handler = WorkflowCapabilityHandler(
        workflow_orchestrator=result.workflow_orchestrator,
        n8n_client=zoom.n8n_client,
        meeting_handler=meeting.meeting_handler,
        conversation_flow_handler=result.conversation_flow_handler,
        auth_service=result.auth_service,
        intern_repo=result.intern_repository,
        logger=logger
    )

    # Wire up workflow handler to query service
    if result.query_service:
        result.query_service.workflow_handler = workflow_capability_handler

    logger.info("Services layer initialized")

    return result


def bootstrap_all(
    app: Flask,
    query_handler_factory: Optional[Callable] = None
) -> BootstrapResult:
    """
    Bootstrap all application components in sequence.

    This is the main entry point for application initialization.
    Each phase builds on the previous, with clear dependencies.

    Args:
        app: Flask application instance
        query_handler_factory: Optional factory to create voice query handler.
            Receives (app, qa_brain) and returns a callable.

    Returns:
        BootstrapResult with all components organized by phase
    """
    # Phase 1: Core infrastructure
    core = bootstrap_phase_1_core(app)

    # Phase 2: GitHub and query processing
    github = bootstrap_phase_2_github(app, core.logger, core.db_path)

    # Phase 3: Zoom integration
    zoom = bootstrap_phase_3_zoom(app, core.logger, core.db_path)

    # Phase 4: Recall.ai meetings
    meeting = bootstrap_phase_4_meetings(app, core.logger, core.db_path)

    # Create voice query handler if factory provided
    query_handler = None
    if query_handler_factory:
        query_handler = query_handler_factory(app, github.qa_brain)

    # Phase 5: Voice and avatar
    voice_avatar = bootstrap_phase_5_voice_avatar(
        app, core.logger, query_handler, meeting.meeting_handler
    )

    # Phase 6: Services layer
    services = bootstrap_phase_6_services(
        app, core.logger, core.db_path, github, zoom, meeting
    )

    return BootstrapResult(
        core=core,
        github=github,
        zoom=zoom,
        meeting=meeting,
        voice_avatar=voice_avatar,
        services=services
    )


def store_components_on_app(app: Flask, result: BootstrapResult) -> None:
    """
    Store all bootstrapped components on the Flask app instance.

    This provides backwards compatibility with code that accesses
    components via app.github_client, app.issue_cache, etc.

    Args:
        app: Flask application instance
        result: Bootstrap result with all components
    """
    # GitHub components
    app.github_client = result.github.github_client
    app.issue_cache = result.github.issue_cache
    app.query_parser = result.github.query_parser
    app.qa_brain = result.github.qa_brain
    app.escalation_manager = result.github.escalation_manager
    app.response_builder = result.github.response_builder

    # Zoom components
    app.n8n_client = result.zoom.n8n_client
    app.zoom_chatbot = result.zoom.zoom_chatbot
    app.zoom_meetings = result.zoom.zoom_meetings

    # Meeting components
    app.meeting_handler = result.meeting.meeting_handler
    app.transcription_processor = result.meeting.transcription_processor

    # Voice/Avatar components
    app.voice_pipeline = result.voice_avatar.voice_pipeline
    app.voice_webhook_handler = result.voice_avatar.voice_webhook_handler
    app.avatar_session_manager = result.voice_avatar.avatar_session_manager

    # Services
    app.rate_limit_service = result.services.rate_limit_service
    app.auth_service = result.services.auth_service
    app.conversation_flow_handler = result.services.conversation_flow_handler
    app.query_service = result.services.query_service
    app.report_service = result.services.report_service
    app.hygiene_service = result.services.hygiene_service
    app.feedback_service = result.services.feedback_service
    app.channel_manager = result.services.channel_manager
    app.workflow_orchestrator = result.services.workflow_orchestrator
    app.meeting_service = result.services.meeting_service

    # Repositories
    app.intern_repository = result.services.intern_repository
    app.query_log_repository = result.services.query_log_repository
    app.workflow_repository = result.services.workflow_repository
    app.meeting_repository = result.services.meeting_repository
    app.conversation_flow_repository = result.services.conversation_flow_repository
    app.audit_repository = result.services.audit_repository


def _load_environment_config(app: Flask) -> None:
    """Load configuration from environment variables into Flask app config."""
    # Zoom configuration
    app.config.setdefault("ZOOM_BOT_TOKEN", os.getenv("ZOOM_BOT_VERIFICATION_TOKEN"))
    app.config.setdefault("ZOOM_BOT_SECRET", os.getenv("ZOOM_BOT_SECRET_TOKEN", ""))
    app.config.setdefault("ZOOM_CLIENT_ID", os.getenv("ZOOM_CLIENT_ID", ""))
    app.config.setdefault("ZOOM_CLIENT_SECRET", os.getenv("ZOOM_CLIENT_SECRET", ""))
    app.config.setdefault("ZOOM_BOT_JID", os.getenv("ZOOM_BOT_JID", ""))
    app.config.setdefault("ZOOM_ACCOUNT_ID", os.getenv("ZOOM_ACCOUNT_ID", ""))
    app.config.setdefault("ZOOM_DEFAULT_CHANNEL_JID", os.getenv("ZOOM_DEFAULT_CHANNEL_JID", ""))

    # Server-to-Server OAuth credentials
    app.config.setdefault("ZOOM_S2S_CLIENT_ID", os.getenv("ZOOM_S2S_CLIENT_ID", ""))
    app.config.setdefault("ZOOM_S2S_CLIENT_SECRET", os.getenv("ZOOM_S2S_CLIENT_SECRET", ""))
    app.config.setdefault("ZOOM_S2S_ACCOUNT_ID", os.getenv("ZOOM_S2S_ACCOUNT_ID", ""))

    # GitHub configuration
    app.config.setdefault("GITHUB_TOKEN", os.getenv("GITHUB_TOKEN"))
    app.config.setdefault("GITHUB_ORG", os.getenv("GITHUB_ORG", "cloudwarriors-ai"))

    # General configuration
    app.config.setdefault("ESCALATION_CONTACT", os.getenv("ESCALATION_CONTACT", "@team"))
    app.config.setdefault("DB_PATH", os.getenv("DB_PATH", "data/state.db"))
    app.config.setdefault("CACHE_TTL", int(os.getenv("CACHE_TTL", "60")))
    app.config.setdefault("RATE_LIMIT", int(os.getenv("RATE_LIMIT", "20")))
    app.config.setdefault("N8N_WEBHOOK_URL", os.getenv("N8N_WEBHOOK_URL", ""))
    app.config.setdefault("N8N_CALLBACK_SECRET", os.getenv("N8N_CALLBACK_SECRET", ""))

    # API authentication
    app.config.setdefault("API_KEY", os.getenv("API_KEY", ""))

    # Recall.ai configuration
    app.config.setdefault("RECALL_API_KEY", os.getenv("RECALL_API_KEY", ""))
    app.config.setdefault("RECALL_BOT_NAME", os.getenv("RECALL_BOT_NAME", "QA Bot"))
    app.config.setdefault("RECALL_BOT_IMAGE", os.getenv("RECALL_BOT_IMAGE", ""))
    app.config.setdefault("RECALL_TRANSCRIPTION_SECRET", os.getenv("RECALL_TRANSCRIPTION_SECRET", ""))
    app.config.setdefault("MEETING_RATE_LIMIT", int(os.getenv("MEETING_RATE_LIMIT", "5")))

    # Voice configuration
    app.config.setdefault("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    app.config.setdefault("CARTESIA_API_KEY", os.getenv("CARTESIA_API_KEY", ""))
    raw_voice = os.getenv("VOICE_ENABLED", "false")
    voice_bool = raw_voice.lower() == "true"
    app.config["VOICE_ENABLED"] = voice_bool

    # Avatar configuration
    app.config.setdefault("SIMLI_API_KEY", os.getenv("SIMLI_API_KEY", ""))
    app.config.setdefault("AVATAR_ENABLED", os.getenv("AVATAR_ENABLED", "false").lower() == "true")
    app.config.setdefault("AVATAR_FACE_ID", os.getenv("AVATAR_FACE_ID", ""))
    app.config.setdefault("AVATAR_PAGE_BASE_URL", os.getenv("AVATAR_PAGE_BASE_URL", ""))

    # Public URL
    app.config.setdefault("PUBLIC_URL", os.getenv("PUBLIC_URL", ""))

    # LLM configuration
    app.config.setdefault("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
    app.config.setdefault("LLM_MODEL", os.getenv("MODEL", "anthropic/claude-haiku-4.5"))

    # Repos list
    repos_env = os.getenv("REPOS", "")
    app.config.setdefault("REPOS", repos_env.split(",") if repos_env else [])


class ConfigurationError(Exception):
    """Raised when critical production configuration is missing."""
    pass


def _validate_production_config(app: Flask, logger: logging.Logger) -> list[str]:
    """
    Validate required configuration for production deployment.

    SECURITY: In production mode, missing critical config will RAISE an exception
    to prevent the app from starting in an insecure state.

    Returns list of warnings for non-critical missing config.
    Raises ConfigurationError for critical missing config in production.
    """
    warnings = []
    critical_errors = []

    is_production = not (app.config.get("TESTING") or app.debug)

    if is_production:
        # CRITICAL security checks - app will NOT start without these
        if not app.config.get("API_KEY"):
            critical_errors.append("API_KEY not set - API endpoints would be unprotected")

        if not app.config.get("ZOOM_BOT_SECRET"):
            critical_errors.append("ZOOM_BOT_SECRET not set - webhook verification disabled")

        if not app.config.get("RECALL_TRANSCRIPTION_SECRET"):
            critical_errors.append("RECALL_TRANSCRIPTION_SECRET not set - Recall webhooks unverified")

        # Non-critical but important - app can start but with reduced functionality
        if not app.config.get("GITHUB_TOKEN"):
            warnings.append("GITHUB_TOKEN not set - GitHub integration disabled")

        if not app.config.get("OPENROUTER_API_KEY"):
            warnings.append("OPENROUTER_API_KEY not set - LLM brain disabled")

        # Log warnings
        for warning in warnings:
            logger.warning(f"PRODUCTION CONFIG WARNING: {warning}")

        # FAIL FAST: Raise exception for critical config errors
        if critical_errors:
            for error in critical_errors:
                logger.error(f"PRODUCTION CONFIG CRITICAL: {error}")
            raise ConfigurationError(
                f"Cannot start in production mode: {len(critical_errors)} critical configuration error(s):\n"
                + "\n".join(f"  - {e}" for e in critical_errors)
            )

    return warnings
