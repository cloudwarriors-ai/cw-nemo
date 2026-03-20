"""
Centralized configuration for QA Bot.

Extracts magic numbers and provides environment-variable-driven configuration
with sensible defaults. All configurable values should be defined here.

Usage:
    from .config import Config
    config = Config()
    timeout = config.llm_timeout
"""
import os
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMConfig:
    """Configuration for LLM Brain (OpenRouter)."""
    api_key: str = ""
    model: str = "anthropic/claude-haiku-4.5"
    timeout_seconds: int = 5
    max_retries: int = 2
    retry_backoff_factor: float = 0.5
    max_tokens: int = 500
    temperature: float = 0.3
    max_repos_in_prompt: int = 20  # Limit repos to avoid token bloat

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Create config from environment variables."""
        return cls(
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
            model=os.getenv("MODEL", "anthropic/claude-haiku-4.5"),
            timeout_seconds=int(os.getenv("LLM_TIMEOUT", "5")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
            retry_backoff_factor=float(os.getenv("LLM_RETRY_BACKOFF", "0.5")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "500")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
            max_repos_in_prompt=int(os.getenv("LLM_MAX_REPOS_IN_PROMPT", "20")),
        )


@dataclass
class CacheConfig:
    """Configuration for issue cache."""
    ttl_seconds: int = 60
    stale_days: int = 14  # Days without update before issue is "stale"

    @classmethod
    def from_env(cls) -> "CacheConfig":
        """Create config from environment variables."""
        return cls(
            ttl_seconds=int(os.getenv("CACHE_TTL", "60")),
            stale_days=int(os.getenv("STALE_DAYS", "14")),
        )


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    chat_requests_per_hour: int = 20
    meeting_joins_per_hour: int = 5

    @classmethod
    def from_env(cls) -> "RateLimitConfig":
        """Create config from environment variables."""
        return cls(
            chat_requests_per_hour=int(os.getenv("RATE_LIMIT", "20")),
            meeting_joins_per_hour=int(os.getenv("MEETING_RATE_LIMIT", "5")),
        )


@dataclass
class InputSanitizationConfig:
    """Configuration for input sanitization."""
    max_input_length: int = 500
    max_response_length: int = 4000
    max_username_length: int = 50

    @classmethod
    def from_env(cls) -> "InputSanitizationConfig":
        """Create config from environment variables."""
        return cls(
            max_input_length=int(os.getenv("MAX_INPUT_LENGTH", "500")),
            max_response_length=int(os.getenv("MAX_RESPONSE_LENGTH", "4000")),
            max_username_length=int(os.getenv("MAX_USERNAME_LENGTH", "50")),
        )


@dataclass
class DeduplicationConfig:
    """Configuration for message deduplication."""
    ttl_seconds: int = 60  # How long to remember processed messages

    @classmethod
    def from_env(cls) -> "DeduplicationConfig":
        """Create config from environment variables."""
        return cls(
            ttl_seconds=int(os.getenv("MESSAGE_DEDUP_TTL", "60")),
        )


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker pattern."""
    failure_threshold: int = 5  # Failures before opening circuit
    recovery_timeout_seconds: int = 30  # Time before trying again
    half_open_requests: int = 1  # Requests to allow in half-open state

    @classmethod
    def from_env(cls) -> "CircuitBreakerConfig":
        """Create config from environment variables."""
        return cls(
            failure_threshold=int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5")),
            recovery_timeout_seconds=int(os.getenv("CIRCUIT_BREAKER_RECOVERY", "30")),
            half_open_requests=int(os.getenv("CIRCUIT_BREAKER_HALF_OPEN", "1")),
        )


@dataclass
class MeetingConfig:
    """Configuration for meeting/Recall.ai integration."""
    cleanup_stale_minutes: int = 30  # Minutes before joining/waiting meetings abandoned
    cleanup_old_days: int = 30  # Days before completed meetings deleted

    @classmethod
    def from_env(cls) -> "MeetingConfig":
        """Create config from environment variables."""
        return cls(
            cleanup_stale_minutes=int(os.getenv("MEETING_CLEANUP_STALE_MINUTES", "30")),
            cleanup_old_days=int(os.getenv("MEETING_CLEANUP_OLD_DAYS", "30")),
        )


@dataclass
class LoggingConfig:
    """Configuration for logging."""
    error_truncate_length: int = 200  # Max length for error messages
    query_log_length: int = 100  # Max length for queries in logs
    request_id_length: int = 8  # Length of request ID prefix

    @classmethod
    def from_env(cls) -> "LoggingConfig":
        """Create config from environment variables."""
        return cls(
            error_truncate_length=int(os.getenv("ERROR_TRUNCATE_LENGTH", "200")),
            query_log_length=int(os.getenv("QUERY_LOG_LENGTH", "100")),
            request_id_length=int(os.getenv("REQUEST_ID_LENGTH", "8")),
        )


@dataclass
class GitHubConfig:
    """Configuration for GitHub API."""
    timeout_seconds: int = 10
    max_retries: int = 3
    retry_backoff_factor: float = 0.5

    @classmethod
    def from_env(cls) -> "GitHubConfig":
        """Create config from environment variables."""
        return cls(
            timeout_seconds=int(os.getenv("GITHUB_TIMEOUT", "10")),
            max_retries=int(os.getenv("GITHUB_MAX_RETRIES", "3")),
            retry_backoff_factor=float(os.getenv("GITHUB_RETRY_BACKOFF", "0.5")),
        )


@dataclass
class TimeoutConfig:
    """
    Centralized timeout configuration with a clear hierarchy.

    Timeout Tiers:
    - INSTANT (1-2s): Health checks, internal operations, cache lookups
    - FAST (5s): LLM queries, quick API calls, queue operations
    - NORMAL (10-15s): Standard API calls (Zoom, GitHub user lookup)
    - SLOW (30s): Complex operations (GitHub bulk fetch, TTS, video generation)
    - EXTENDED (60s): File uploads, batch operations

    Circuit Breaker Timeouts:
    - RECOVERY (60s): Time before retrying after circuit opens

    All values in seconds unless otherwise noted.
    """
    # Tier 1: INSTANT (1-2s) - internal operations
    instant: int = 2
    health_check: int = 2

    # Tier 2: FAST (5s) - quick operations
    fast: int = 5
    llm_query: int = 5
    queue_operation: float = 0.5  # Internal queue timeout

    # Tier 3: NORMAL (10-15s) - standard API calls
    normal: int = 10
    zoom_api: int = 10
    github_user: int = 10
    websocket_receive: int = 10

    # Tier 4: SLOW (30s) - complex operations
    slow: int = 30
    github_bulk: int = 30
    recall_api: int = 30
    n8n_workflow: int = 30
    tts_synthesis: int = 30
    video_generation: int = 30

    # Tier 5: EXTENDED (60s) - batch/file operations
    extended: int = 60
    file_upload: int = 60
    meeting_wait: int = 120  # Waiting for meeting status changes

    # Circuit breaker recovery
    circuit_recovery: int = 60

    @classmethod
    def from_env(cls) -> "TimeoutConfig":
        """Create config from environment variables."""
        return cls(
            # Tier 1
            instant=int(os.getenv("TIMEOUT_INSTANT", "2")),
            health_check=int(os.getenv("TIMEOUT_HEALTH_CHECK", "2")),
            # Tier 2
            fast=int(os.getenv("TIMEOUT_FAST", "5")),
            llm_query=int(os.getenv("LLM_TIMEOUT", "5")),
            queue_operation=float(os.getenv("TIMEOUT_QUEUE", "0.5")),
            # Tier 3
            normal=int(os.getenv("TIMEOUT_NORMAL", "10")),
            zoom_api=int(os.getenv("TIMEOUT_ZOOM_API", "10")),
            github_user=int(os.getenv("TIMEOUT_GITHUB_USER", "10")),
            websocket_receive=int(os.getenv("TIMEOUT_WEBSOCKET", "10")),
            # Tier 4
            slow=int(os.getenv("TIMEOUT_SLOW", "30")),
            github_bulk=int(os.getenv("GITHUB_TIMEOUT", "30")),
            recall_api=int(os.getenv("TIMEOUT_RECALL_API", "30")),
            n8n_workflow=int(os.getenv("TIMEOUT_N8N_WORKFLOW", "30")),
            tts_synthesis=int(os.getenv("TIMEOUT_TTS", "30")),
            video_generation=int(os.getenv("TIMEOUT_VIDEO_GEN", "30")),
            # Tier 5
            extended=int(os.getenv("TIMEOUT_EXTENDED", "60")),
            file_upload=int(os.getenv("TIMEOUT_FILE_UPLOAD", "60")),
            meeting_wait=int(os.getenv("TIMEOUT_MEETING_WAIT", "120")),
            # Circuit breaker
            circuit_recovery=int(os.getenv("CIRCUIT_BREAKER_RECOVERY", "60")),
        )


@dataclass
class AuthorizationConfig:
    """Configuration for role-based authorization."""

    # Comma-separated list of Zoom user IDs authorized for onboarding/offboarding
    authorized_onboarding_users: list[str] = field(default_factory=list)

    # Comma-separated list of email domains allowed for interns
    allowed_email_domains: list[str] = field(default_factory=list)

    # Conversation flow timeout in minutes
    flow_timeout_minutes: int = 15

    @classmethod
    def from_env(cls) -> "AuthorizationConfig":
        """Create config from environment variables."""
        # Parse comma-separated user IDs
        users_str = os.getenv("AUTHORIZED_ONBOARDING_USERS", "")
        users = [u.strip() for u in users_str.split(",") if u.strip()]

        # Parse comma-separated domains
        domains_str = os.getenv("ALLOWED_EMAIL_DOMAINS", "")
        domains = [d.strip() for d in domains_str.split(",") if d.strip()]

        return cls(
            authorized_onboarding_users=users,
            allowed_email_domains=domains,
            flow_timeout_minutes=int(os.getenv("FLOW_TIMEOUT_MINUTES", "15")),
        )


@dataclass
class OnboardingConfig:
    """Configuration for onboarding documentation links and workflows."""

    # Key documentation links
    links: dict = field(default_factory=lambda: {
        "orientation_presentation": {
            "title": "Orientation Presentation",
            "url": "https://docs.google.com/presentation/d/1AUYLuU5KK4jFfdDUlW41wBadSDEMC_nc/edit?usp=drive_link",
            "description": "New hire/intern orientation slides"
        },
        "issue_guide": {
            "title": "GitHub Issue Management Guide",
            "url": "https://docs.google.com/document/d/1o__QhVgJCe-67nIQ771-zFHGwTsaIRTIiAEHD5PPof0/edit?usp=drive_link",
            "description": "How to create, label, and manage GitHub issues"
        },
        "weekly_checklist": {
            "title": "Weekly Application Checklist",
            "url": "https://docs.google.com/document/d/1FtUBvQ43VmC7re0QLMAXOD3X1fwVmbDGMwcDI7sJ4T8/edit?usp=drive_link",
            "description": "Weekly QA health check tasks"
        },
        "change_control": {
            "title": "Change Control Process",
            "url": "https://drive.google.com/file/d/13TAGxJrzHbFmbcgiE9xaWrKZHJFCnk4y/view?usp=drive_link",
            "description": "CAB review and change management process"
        },
        "issue_tracker": {
            "title": "GitHub Issue Tracker",
            "url": "https://cw-gh-tracker.cloudwarriors.ai/",
            "description": "Dashboard for tracking GitHub issues"
        },
    })

    # Key contacts for onboarding
    contacts: dict = field(default_factory=lambda: {
        "leadership": {"name": "Doug", "role": "CSD Leadership, feedback coordination"},
        "hr": {"name": "Kindra", "role": "HR, SkillBridge coordination, interviews"},
        "technical": {"name": "Chad", "role": "Technical, onboarding support"},
        "onboarding_support": {"name": "Trent", "role": "Onboarding support"},
    })

    # Meeting schedule for reference
    meetings: list = field(default_factory=lambda: [
        {"name": "DevOps Morning Meeting", "frequency": "Daily", "time": "1030 EST"},
        {"name": "CAB Review", "frequency": "Weekly", "time": "Monday"},
        {"name": "Intern/New Hire Onboarding", "frequency": "As needed", "time": "0930 EST"},
        {"name": "Weekly Feedback (Interns)", "frequency": "Weekly", "time": "Friday Afternoon"},
    ])

    # Recurring Zoom meetings to add new interns to
    # Each has name and meeting_id for registration
    recurring_meetings: list = field(default_factory=lambda: [
        {"name": "DevOps Morning Meeting", "meeting_id": "81180522212", "time": "1030 EST Daily"},
        {"name": "DevOps Change Window", "meeting_id": "89525847659", "time": "Thursday"},
        {"name": "DevOps Friday Meeting", "meeting_id": "84177121646", "time": "Friday"},
    ])

    # Zoom meeting IDs to add interns to (comma-separated in env, for backwards compat)
    zoom_meeting_ids: list[str] = field(default_factory=list)

    # Exit survey URL for offboarding
    exit_survey_url: str = ""

    # Orientation presentation URL
    orientation_presentation_url: str = "https://docs.google.com/presentation/d/1AUYLuU5KK4jFfdDUlW41wBadSDEMC_nc/edit?usp=drive_link"

    @classmethod
    def from_env(cls) -> "OnboardingConfig":
        """Create config from environment variables."""
        # Parse comma-separated meeting IDs (for backwards compatibility)
        meetings_str = os.getenv("ONBOARDING_ZOOM_MEETING_IDS", "")
        meeting_ids = [m.strip() for m in meetings_str.split(",") if m.strip()]

        # If no env var, use the default recurring meetings
        if not meeting_ids:
            meeting_ids = ["81180522212", "89525847659", "84177121646"]

        return cls(
            zoom_meeting_ids=meeting_ids,
            exit_survey_url=os.getenv("EXIT_SURVEY_URL", ""),
            orientation_presentation_url=os.getenv(
                "ORIENTATION_PRESENTATION_URL",
                "https://docs.google.com/presentation/d/1AUYLuU5KK4jFfdDUlW41wBadSDEMC_nc/edit?usp=drive_link"
            ),
        )


@dataclass
class Config:
    """
    Master configuration object containing all sub-configurations.

    Use Config.from_env() to create from environment variables.
    """
    llm: LLMConfig = field(default_factory=LLMConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    input: InputSanitizationConfig = field(default_factory=InputSanitizationConfig)
    dedup: DeduplicationConfig = field(default_factory=DeduplicationConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    meeting: MeetingConfig = field(default_factory=MeetingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    timeout: TimeoutConfig = field(default_factory=TimeoutConfig)
    authorization: AuthorizationConfig = field(default_factory=AuthorizationConfig)
    onboarding: OnboardingConfig = field(default_factory=OnboardingConfig)

    @classmethod
    def from_env(cls) -> "Config":
        """Create full configuration from environment variables."""
        return cls(
            llm=LLMConfig.from_env(),
            cache=CacheConfig.from_env(),
            rate_limit=RateLimitConfig.from_env(),
            input=InputSanitizationConfig.from_env(),
            dedup=DeduplicationConfig.from_env(),
            circuit_breaker=CircuitBreakerConfig.from_env(),
            meeting=MeetingConfig.from_env(),
            logging=LoggingConfig.from_env(),
            github=GitHubConfig.from_env(),
            timeout=TimeoutConfig.from_env(),
            authorization=AuthorizationConfig.from_env(),
            onboarding=OnboardingConfig.from_env(),
        )


# Singleton instance - load once at import
_config: Optional[Config] = None
_config_lock = threading.Lock()


def get_config() -> Config:
    """
    Get the global configuration singleton.

    Thread-safe - uses double-checked locking pattern.
    """
    global _config
    if _config is None:
        with _config_lock:
            # Double-check inside lock
            if _config is None:
                _config = Config.from_env()
    return _config


def reset_config() -> None:
    """Reset config (useful for testing)."""
    global _config
    with _config_lock:
        _config = None


# HTTP status codes used in responses
class HttpStatus:
    """Standard HTTP status codes."""
    OK = 200
    CREATED = 201
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    NOT_FOUND = 404
    TOO_MANY_REQUESTS = 429
    INTERNAL_ERROR = 500
    SERVICE_UNAVAILABLE = 503


# Bot mention prefixes to strip from messages
BOT_MENTIONS = ["@qa bot", "@qabot", "@qa-bot", "@qa_bot"]
