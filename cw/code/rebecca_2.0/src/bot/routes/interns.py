"""
Intern management endpoints.

Handles CRUD operations for interns and their tasks.
Uses InternRepository for data access.
"""
import uuid
from flask import Blueprint, request, jsonify, current_app, g

interns_bp = Blueprint("interns", __name__, url_prefix="/api")


def _get_intern_repository():
    """Get InternRepository from app context."""
    if hasattr(current_app, 'intern_repository') and current_app.intern_repository:
        return current_app.intern_repository
    # Fallback for tests or when repository not initialized
    from ..repositories import InternRepository
    return InternRepository(db_path=current_app.config["DB_PATH"])


@interns_bp.route("/interns", methods=["GET"])
def list_interns():
    """
    List all interns.

    Query params:
        status: Filter by status (onboarding, active, graduating, completed)
        include_tasks: Include task counts (true/false)
    """
    status = request.args.get("status")
    include_tasks = request.args.get("include_tasks", "").lower() == "true"

    try:
        repo = _get_intern_repository()
        interns = repo.get_all(status=status, include_tasks=include_tasks)
        return jsonify({"interns": interns, "count": len(interns)})
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] List interns error: {e}", exc_info=True)
        return jsonify({"error": "Failed to list interns"}), 500


@interns_bp.route("/intern/<intern_id>", methods=["GET"])
def get_intern(intern_id: str):
    """Get intern details by ID."""
    try:
        repo = _get_intern_repository()
        intern = repo.get_by_id(intern_id)
        if not intern:
            return jsonify({"error": "Intern not found"}), 404

        tasks = repo.get_tasks(intern_id)
        intern["tasks"] = tasks
        return jsonify(intern)
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Get intern error: {e}", exc_info=True)
        return jsonify({"error": "Failed to get intern"}), 500


@interns_bp.route("/intern/<intern_id>/tasks", methods=["GET"])
def get_intern_tasks_endpoint(intern_id: str):
    """Get tasks for an intern."""
    status = request.args.get("status")
    since = request.args.get("since")

    try:
        repo = _get_intern_repository()
        tasks = repo.get_tasks(intern_id, status=status, since=since)
        return jsonify({"tasks": tasks, "count": len(tasks)})
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Get intern tasks error: {e}", exc_info=True)
        return jsonify({"error": "Failed to get tasks"}), 500


@interns_bp.route("/intern", methods=["POST"])
def create_intern():
    """
    Create a new intern.

    JSON body:
        name: Intern's full name (required)
        program: Program type (skillbridge, vanderbilt, other)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        supervisor: Supervisor name/mention
        email: Email address
    """
    data = request.json or {}

    # Validate required fields
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Missing required fields: name"}), 400

    try:
        repo = _get_intern_repository()
        # Use provided ID or generate a unique one
        intern_id = data.get("id") or str(uuid.uuid4())[:8]

        success = repo.create(
            intern_id=intern_id,
            name=name,
            program=data.get("program", "other"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            supervisor=data.get("supervisor"),
            email=data.get("email"),
        )
        if not success:
            return jsonify({"error": "Failed to create intern"}), 500

        current_app.logger.info(f"[{g.request_id}] Created intern: {intern_id} ({name})")
        return jsonify({"status": "created", "id": intern_id, "name": name}), 201
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Create intern error: {e}", exc_info=True)
        return jsonify({"error": "Failed to create intern"}), 500


@interns_bp.route("/intern/<intern_id>/status", methods=["PUT"])
def update_intern_status_endpoint(intern_id: str):
    """
    Update an intern's status.

    JSON body:
        status: New status (onboarding, active, graduating, completed)
    """
    data = request.json or {}
    new_status = data.get("status", "").strip()

    valid_statuses = ["onboarding", "active", "graduating", "completed"]
    if new_status not in valid_statuses:
        return jsonify({
            "error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        }), 400

    try:
        repo = _get_intern_repository()
        success = repo.update_status(intern_id, new_status)
        if success:
            current_app.logger.info(f"[{g.request_id}] Updated intern {intern_id} status to {new_status}")
            return jsonify({"status": "updated", "new_status": new_status})
        else:
            return jsonify({"error": "Intern not found"}), 404
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Update intern status error: {e}", exc_info=True)
        return jsonify({"error": "Failed to update status"}), 500


@interns_bp.route("/interns/ending-soon", methods=["GET"])
def get_interns_ending_soon_endpoint():
    """Get interns whose end date is within the specified days."""
    days = request.args.get("days", "14", type=int)

    try:
        repo = _get_intern_repository()
        interns = repo.get_ending_soon(days)
        return jsonify({"interns": interns, "count": len(interns), "days": days})
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Get interns ending soon error: {e}", exc_info=True)
        return jsonify({"error": "Failed to get interns"}), 500
