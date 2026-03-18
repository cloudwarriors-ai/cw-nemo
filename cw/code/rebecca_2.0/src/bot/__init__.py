"""
QA Bot - Interactive Zoom Team Chat bot for QA queries.

This module provides a Flask-based webhook handler that responds to
user queries about GitHub issues, intern status, and QA processes.
"""

from .app import app, create_app
from .query_parser import QueryParser, QueryResult, QueryType
from .cache import IssueCache
from .escalation import EscalationManager
from .response_builder import ResponseBuilder
from .database import init_db, get_intern_status

__all__ = [
    "app",
    "create_app",
    "QueryParser",
    "QueryResult",
    "QueryType",
    "IssueCache",
    "EscalationManager",
    "ResponseBuilder",
    "init_db",
    "get_intern_status",
]
