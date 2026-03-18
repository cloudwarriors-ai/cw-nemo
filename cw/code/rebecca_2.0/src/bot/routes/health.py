"""
Health check and debug endpoints.

Provides system health monitoring and debugging capabilities.
"""

import sqlite3
import time

from flask import Blueprint, request, jsonify, current_app, g

from ..circuit_breaker import get_all_circuit_statuses

health_bp = Blueprint("health", __name__)


@health_bp.route("/health/live", methods=["GET"])
def liveness():
    """
    Kubernetes liveness probe endpoint.

    Checks if the application process is running and responsive.
    This should be fast and always succeed unless the app is deadlocked.

    Use for: Kubernetes livenessProbe
    Failure action: Kubernetes will restart the pod
    """
    return jsonify({
        "status": "ok",
        "timestamp": time.time(),
    }), 200


@health_bp.route("/health/ready", methods=["GET"])
def readiness():
    """
    Kubernetes readiness probe endpoint.

    Checks if the application is ready to serve traffic:
    - Database is accessible
    - No critical circuit breakers are open
    - Core services are initialized

    Use for: Kubernetes readinessProbe
    Failure action: Kubernetes will stop routing traffic to this pod

    Returns:
        200 OK: Ready to serve traffic
        503 Service Unavailable: Not ready (with details)
    """
    checks = {}
    is_ready = True

    # Check 1: Database connectivity (critical)
    try:
        db_path = current_app.config.get("DB_PATH", "data/state.db")
        conn = sqlite3.connect(db_path, timeout=2)
        conn.execute("SELECT 1")
        conn.close()
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)[:100]}
        is_ready = False

    # Check 2: Critical circuit breakers (if any are open, we're degraded)
    circuit_statuses = get_all_circuit_statuses()
    open_circuits = [
        status.get("name", "unknown") for status in circuit_statuses
        if status.get("state") == "open"
    ]
    if open_circuits:
        checks["circuit_breakers"] = {
            "status": "degraded",
            "open_circuits": open_circuits
        }
        # Note: We don't fail readiness for open circuits - that would cause
        # cascading failures. Instead, we mark as degraded but still ready.
    else:
        checks["circuit_breakers"] = {"status": "ok"}

    # Check 3: Cache initialization (if configured)
    if current_app.issue_cache:
        if current_app.issue_cache.has_data:
            checks["cache"] = {"status": "ok"}
        else:
            checks["cache"] = {"status": "initializing"}
            # Not a failure - cache may still be warming up
    else:
        checks["cache"] = {"status": "not_configured"}

    # Check 4: Auth service (critical for security)
    if hasattr(current_app, 'auth_service') and current_app.auth_service:
        checks["auth_service"] = {"status": "ok"}
    else:
        checks["auth_service"] = {"status": "not_configured"}
        # In production, this should have been caught by config validation

    status_code = 200 if is_ready else 503
    return jsonify({
        "status": "ready" if is_ready else "not_ready",
        "timestamp": time.time(),
        "checks": checks,
    }), status_code


@health_bp.route("/health", methods=["GET"])
def health():
    """
    Comprehensive health check endpoint with dependency checks.

    Returns detailed health status for monitoring dashboards.
    Use ?detailed=true for full dependency checks (slower).

    For Kubernetes probes, use /health/live and /health/ready instead.
    """
    detailed = request.args.get("detailed", "false").lower() == "true"

    import os
    status = {
        "status": "ok",
        "timestamp": time.time(),
        "version": os.getenv("APP_VERSION", "1.0.0"),
    }

    # Configuration status (always included)
    public_url = current_app.config.get("PUBLIC_URL", "")
    status["config"] = {
        "github_configured": current_app.github_client is not None,
        "repo_count": len(current_app.config.get("REPOS", [])),
        "meeting_configured": current_app.meeting_handler is not None,
        "voice_enabled": current_app.config.get("VOICE_ENABLED", False),
        "avatar_enabled": current_app.config.get("AVATAR_ENABLED", False),
    }

    # Cache status (always included)
    if current_app.issue_cache:
        status["cache"] = {
            "age_seconds": current_app.issue_cache.age_seconds,
            "ttl_seconds": current_app.config.get("CACHE_TTL", 60),
        }

    # Detailed dependency checks (optional - adds latency)
    if detailed:
        status["dependencies"] = {}
        overall_healthy = True

        # Check GitHub API
        if current_app.github_client:
            try:
                # Rate limit check is fast and doesn't count against quota
                rate_limit = current_app.github_client.get_rate_limit()
                status["dependencies"]["github"] = {
                    "status": "ok",
                    "rate_limit_remaining": rate_limit.get("remaining", 0),
                }
            except Exception as e:
                status["dependencies"]["github"] = {"status": "error", "error": str(e)}
                overall_healthy = False
        else:
            status["dependencies"]["github"] = {"status": "not_configured"}

        # Check issue cache
        if current_app.issue_cache:
            cache_status = "fresh" if current_app.issue_cache.has_data else "empty"
            status["dependencies"]["issue_cache"] = {
                "status": cache_status,
                "issue_count": current_app.issue_cache.issue_count,
                "age_seconds": round(current_app.issue_cache.age_seconds, 1),
            }
        else:
            status["dependencies"]["issue_cache"] = {"status": "not_configured"}

        # Check database
        try:
            db_path = current_app.config.get("DB_PATH", "data/state.db")
            conn = sqlite3.connect(db_path)
            conn.execute("SELECT 1")
            conn.close()
            status["dependencies"]["database"] = {"status": "ok"}
        except Exception as e:
            status["dependencies"]["database"] = {"status": "error", "error": str(e)}
            overall_healthy = False

        # Check n8n client
        if current_app.n8n_client:
            status["dependencies"]["n8n"] = {"status": "configured"}
        else:
            status["dependencies"]["n8n"] = {"status": "not_configured"}

        # Check Recall.ai (if configured)
        if current_app.meeting_handler:
            status["dependencies"]["recall_ai"] = {"status": "configured"}
        else:
            status["dependencies"]["recall_ai"] = {"status": "not_configured"}

        # Check voice pipeline
        if current_app.voice_pipeline:
            status["dependencies"]["voice"] = {"status": "configured"}
        else:
            status["dependencies"]["voice"] = {"status": "not_configured"}

        # Check avatar
        if current_app.avatar_session_manager:
            status["dependencies"]["avatar"] = {
                "status": "configured",
                "active": current_app.avatar_session_manager.is_active,
            }
        else:
            status["dependencies"]["avatar"] = {"status": "not_configured"}

        # Check LLM Brain
        if current_app.qa_brain:
            try:
                brain_health = current_app.qa_brain.get_health_status()
                status["dependencies"]["llm_brain"] = brain_health
                if brain_health.get("status") != "ok":
                    overall_healthy = False
            except Exception as e:
                status["dependencies"]["llm_brain"] = {"status": "error", "error": str(e)}
                overall_healthy = False
        else:
            status["dependencies"]["llm_brain"] = {"status": "not_configured"}

        # Circuit breaker status
        status["circuit_breakers"] = get_all_circuit_statuses()

        if not overall_healthy:
            status["status"] = "degraded"

    return jsonify(status)


@health_bp.route("/debug/code-version")
def debug_code_version():
    """Debug endpoint to verify code is current."""
    return jsonify({
        "version": "refactored-blueprints-v1",
        "timestamp": "2026-01-11",
        "blueprints": ["health", "zoom", "interns", "workflows", "meetings", "voice", "avatar"]
    })


@health_bp.route("/api/cache/refresh", methods=["POST"])
def refresh_cache():
    """
    Manually refresh the GitHub issue cache.

    Triggers a full refresh from GitHub API. Returns status and timing.
    This is the ONLY way to refresh the cache - no automatic background refresh.
    """
    if not current_app.issue_cache:
        return jsonify({
            "success": False,
            "error": "Issue cache not configured"
        }), 400

    result = current_app.issue_cache.refresh()
    status_code = 200 if result.get("success") else 500

    return jsonify(result), status_code


@health_bp.route("/api/cache/status", methods=["GET"])
def cache_status():
    """
    Get current cache status.

    Returns cache age, issue count, and refresh status.
    """
    if not current_app.issue_cache:
        return jsonify({
            "configured": False,
            "error": "Issue cache not configured"
        }), 400

    cache = current_app.issue_cache
    return jsonify({
        "configured": True,
        "has_data": cache.has_data,
        "issue_count": cache.issue_count,
        "age_seconds": round(cache.age_seconds, 1),
        "is_refreshing": cache._is_fetching,
        "repos_monitored": len(cache.repos),
    })
