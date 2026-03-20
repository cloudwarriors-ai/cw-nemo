"""
GitHub organization management endpoints.

Called by n8n workflows and internal services to manage GitHub org members.
"""

from flask import Blueprint, request, jsonify, current_app, g

from ..middleware import require_internal_auth

github_bp = Blueprint("github", __name__)


def _get_audit_repository():
    """Get AuditRepository from app context."""
    if hasattr(current_app, 'audit_repository') and current_app.audit_repository:
        return current_app.audit_repository
    from ..repositories import AuditRepository
    return AuditRepository(db_path=current_app.config["DB_PATH"])


@github_bp.route("/api/github/invite", methods=["POST"])
@require_internal_auth
def invite_to_org():
    """
    Invite a user to the GitHub organization.

    Called by n8n onboarding workflow after intern details are collected.

    JSON body:
        username: GitHub username to invite (required)
        intern_id: Intern ID for audit logging (optional)
        role: Organization role - "member" or "admin" (default: member)

    Returns:
        success: True if invitation sent or user already a member
        state: "pending" (invitation sent) or "active" (already member)
        message: Human-readable status message
        error: Error message if failed
    """
    if not hasattr(current_app, 'github_client') or not current_app.github_client:
        return jsonify({
            "success": False,
            "error": "GitHub client not configured"
        }), 503

    data = request.json or {}
    username = data.get("username", "").strip()
    intern_id = data.get("intern_id")
    role = data.get("role", "member")

    if not username:
        return jsonify({
            "success": False,
            "error": "username is required"
        }), 400

    if role not in ("member", "admin"):
        role = "member"

    try:
        result = current_app.github_client.invite_to_org(username, role=role)

        # Log for audit trail
        import json
        audit_repo = _get_audit_repository()
        audit_repo.log_event(
            action="github_invite",
            target_id=intern_id,
            target_name=username,
            actor_user_id="n8n_workflow",
            actor_name="n8n Onboarding Workflow",
            details=json.dumps({
                "success": result.get("success"),
                "state": result.get("state"),
                "role": role
            })
        )

        if result.get("success"):
            current_app.logger.info(
                f"[{g.request_id}] GitHub invite: {username} -> {result.get('state')}"
            )
            return jsonify(result)
        else:
            current_app.logger.warning(
                f"[{g.request_id}] GitHub invite failed: {username} - {result.get('error')}"
            )
            return jsonify(result), 400

    except Exception as e:
        current_app.logger.error(
            f"[{g.request_id}] GitHub invite error for {username}: {e}",
            exc_info=True
        )
        return jsonify({
            "success": False,
            "error": f"Failed to invite user: {str(e)}"
        }), 500


@github_bp.route("/api/github/remove", methods=["POST"])
@require_internal_auth
def remove_from_org():
    """
    Remove a user from the GitHub organization.

    Called by n8n offboarding workflow during intern offboarding.

    JSON body:
        username: GitHub username to remove (required)
        intern_id: Intern ID for audit logging (optional)

    Returns:
        success: True if user removed or wasn't a member
        message: Human-readable status message
        error: Error message if failed
    """
    if not hasattr(current_app, 'github_client') or not current_app.github_client:
        return jsonify({
            "success": False,
            "error": "GitHub client not configured"
        }), 503

    data = request.json or {}
    username = data.get("username", "").strip()
    intern_id = data.get("intern_id")

    if not username:
        return jsonify({
            "success": False,
            "error": "username is required"
        }), 400

    try:
        result = current_app.github_client.remove_from_org(username)

        # Log for audit trail
        import json
        audit_repo = _get_audit_repository()
        audit_repo.log_event(
            action="github_remove",
            target_id=intern_id,
            target_name=username,
            actor_user_id="n8n_workflow",
            actor_name="n8n Offboarding Workflow",
            details=json.dumps({
                "success": result.get("success"),
                "was_member": "not a member" not in result.get("message", "").lower()
            })
        )

        if result.get("success"):
            current_app.logger.info(
                f"[{g.request_id}] GitHub remove: {username}"
            )
            return jsonify(result)
        else:
            current_app.logger.warning(
                f"[{g.request_id}] GitHub remove failed: {username} - {result.get('error')}"
            )
            return jsonify(result), 400

    except Exception as e:
        current_app.logger.error(
            f"[{g.request_id}] GitHub remove error for {username}: {e}",
            exc_info=True
        )
        return jsonify({
            "success": False,
            "error": f"Failed to remove user: {str(e)}"
        }), 500


@github_bp.route("/api/github/validate", methods=["POST"])
@require_internal_auth
def validate_user():
    """
    Validate a GitHub username exists.

    Called during onboarding to verify username before proceeding.

    JSON body:
        username: GitHub username to validate (required)

    Returns:
        exists: True if user exists on GitHub
        login: Actual GitHub login (case-corrected)
        name: User's display name
        avatar_url: User's avatar URL
        profile_url: Link to GitHub profile
        error: Error message if user not found
    """
    if not hasattr(current_app, 'github_client') or not current_app.github_client:
        return jsonify({
            "exists": False,
            "error": "GitHub client not configured"
        }), 503

    data = request.json or {}
    username = data.get("username", "").strip()

    if not username:
        return jsonify({
            "exists": False,
            "error": "username is required"
        }), 400

    try:
        result = current_app.github_client.validate_github_user(username)
        return jsonify(result)

    except Exception as e:
        current_app.logger.error(
            f"[{g.request_id}] GitHub validate error for {username}: {e}",
            exc_info=True
        )
        return jsonify({
            "exists": False,
            "error": f"Validation failed: {str(e)}"
        }), 500


@github_bp.route("/api/github/membership", methods=["POST"])
@require_internal_auth
def check_membership():
    """
    Check a user's organization membership status.

    JSON body:
        username: GitHub username to check (required)

    Returns:
        is_member: True if user is an org member
        role: "member", "admin", or None
        state: "active", "pending", or None
    """
    if not hasattr(current_app, 'github_client') or not current_app.github_client:
        return jsonify({
            "is_member": False,
            "error": "GitHub client not configured"
        }), 503

    data = request.json or {}
    username = data.get("username", "").strip()

    if not username:
        return jsonify({
            "is_member": False,
            "error": "username is required"
        }), 400

    try:
        result = current_app.github_client.get_org_membership(username)
        return jsonify(result)

    except Exception as e:
        current_app.logger.error(
            f"[{g.request_id}] GitHub membership check error for {username}: {e}",
            exc_info=True
        )
        return jsonify({
            "is_member": False,
            "error": f"Membership check failed: {str(e)}"
        }), 500
