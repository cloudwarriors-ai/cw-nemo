"""
Session limit tracking for external API calls.

Tracks API call counts to prevent hitting rate limits on external services.
Limits are defined in CLAUDE.md and enforced here.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

logger = logging.getLogger("qa_agent.session_limits")

# Hard limits per session (from CLAUDE.md)
SERVICE_LIMITS = {
    "simli": {"max_calls": 2, "health_check": 1},
    "recall_ai": {"max_calls": 3, "health_check": 1},
    "openai": {"max_calls": 5, "health_check": None},  # unlimited health checks
    "livekit": {"max_calls": 5, "health_check": None},
    "cartesia": {"max_calls": 3, "health_check": 1},
    "deepgram": {"max_calls": 3, "health_check": 1},
}

# Path to session limits file
LIMITS_FILE = Path(__file__).parent.parent.parent / ".claude" / "session_limits.json"

# Thread lock for file access
_lock = Lock()


def _ensure_limits_file() -> Dict:
    """Ensure limits file exists and return current state."""
    LIMITS_FILE.parent.mkdir(parents=True, exist_ok=True)

    if LIMITS_FILE.exists():
        try:
            with open(LIMITS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Create default state
    default = {
        "session_start": datetime.utcnow().isoformat() + "Z",
        "calls": {service: 0 for service in SERVICE_LIMITS.keys()},
        "notes": "Tracks API calls per session to prevent rate limits"
    }
    _save_limits(default)
    return default


def _save_limits(data: Dict) -> None:
    """Save limits data to file."""
    with open(LIMITS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_call_count(service: str) -> int:
    """Get current call count for a service."""
    with _lock:
        data = _ensure_limits_file()
        return data.get("calls", {}).get(service, 0)


def get_remaining_calls(service: str) -> int:
    """Get remaining calls allowed for a service."""
    limit_info = SERVICE_LIMITS.get(service, {})
    max_calls = limit_info.get("max_calls", 0)
    current = get_call_count(service)
    return max(0, max_calls - current)


def can_call_service(service: str, is_health_check: bool = False) -> bool:
    """
    Check if we can make a call to the service.

    Args:
        service: Service name (simli, recall_ai, etc.)
        is_health_check: If True, uses health check limit instead

    Returns:
        True if call is allowed
    """
    limit_info = SERVICE_LIMITS.get(service)
    if not limit_info:
        logger.warning(f"Unknown service: {service}, allowing call")
        return True

    current = get_call_count(service)
    max_calls = limit_info.get("max_calls", 0)

    # Health checks have separate (usually more generous) limits
    if is_health_check:
        health_limit = limit_info.get("health_check")
        if health_limit is None:  # Unlimited health checks
            return True
        # Health checks don't count against main limit
        return True

    if current >= max_calls:
        logger.error(
            f"RATE LIMIT: {service} at limit ({current}/{max_calls}). "
            f"Cannot make more calls this session."
        )
        return False

    return True


def record_call(service: str, is_health_check: bool = False) -> bool:
    """
    Record an API call to a service.

    Args:
        service: Service name
        is_health_check: If True, doesn't count against main limit

    Returns:
        True if recorded, False if at limit
    """
    if not can_call_service(service, is_health_check):
        return False

    if is_health_check:
        # Health checks don't count against main limit
        logger.debug(f"Health check to {service} (not counted)")
        return True

    with _lock:
        data = _ensure_limits_file()
        if "calls" not in data:
            data["calls"] = {}

        current = data["calls"].get(service, 0)
        data["calls"][service] = current + 1
        _save_limits(data)

        limit_info = SERVICE_LIMITS.get(service, {})
        max_calls = limit_info.get("max_calls", "?")
        logger.info(f"Recorded {service} call: {current + 1}/{max_calls}")

    return True


def reset_session() -> None:
    """Reset all call counts for a new session."""
    with _lock:
        data = {
            "session_start": datetime.utcnow().isoformat() + "Z",
            "calls": {service: 0 for service in SERVICE_LIMITS.keys()},
            "notes": "Session reset"
        }
        _save_limits(data)
        logger.info("Session limits reset")


def get_status() -> Dict:
    """Get current status of all service limits."""
    with _lock:
        data = _ensure_limits_file()

    status = {}
    for service, limit_info in SERVICE_LIMITS.items():
        current = data.get("calls", {}).get(service, 0)
        max_calls = limit_info.get("max_calls", 0)
        status[service] = {
            "current": current,
            "max": max_calls,
            "remaining": max(0, max_calls - current),
            "at_limit": current >= max_calls,
        }

    return {
        "session_start": data.get("session_start"),
        "services": status,
    }
