"""
Service layer for QA Bot.

Services contain business logic extracted from routes, promoting:
- Single Responsibility Principle
- Testability
- Code reuse across blueprints
"""

from .rate_limit_service import RateLimitService
from .query_service import QueryService
from .auth_service import AuthService
from .report_service import ReportService
from .hygiene_service import HygieneService
from .feedback_service import FeedbackService
from .workflow_orchestrator import WorkflowOrchestrator, WorkflowResult
from .conversation_flow import ConversationFlowHandler, FlowResponse
from .workflow_capability_handler import WorkflowCapabilityHandler
from .flow_completion_handler import FlowCompletionHandler, CompletionResult
from .meeting_service import MeetingService, MeetingJoinResult, AvatarConfig
from .query_context import QueryContext

__all__ = [
    "RateLimitService",
    "QueryService",
    "AuthService",
    "ReportService",
    "HygieneService",
    "FeedbackService",
    "WorkflowOrchestrator",
    "WorkflowResult",
    "ConversationFlowHandler",
    "FlowResponse",
    "WorkflowCapabilityHandler",
    "FlowCompletionHandler",
    "CompletionResult",
    "MeetingService",
    "MeetingJoinResult",
    "AvatarConfig",
    "QueryContext",
]
