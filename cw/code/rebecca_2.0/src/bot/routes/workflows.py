"""
n8n workflow endpoints.

Handles workflow triggers and callbacks from n8n.
"""

from flask import Blueprint, request, jsonify, current_app, g

from ..config import get_config
from ..middleware import require_api_auth

workflows_bp = Blueprint("workflows", __name__)
_config = get_config()


@workflows_bp.route("/api/workflow/trigger", methods=["POST"])
@require_api_auth
def trigger_workflow():
    """
    Trigger an n8n workflow.

    JSON body:
        workflow: Workflow name (onboarding, offboarding, weekly_feedback, health_check)
        data: Workflow-specific data
    """
    if not current_app.n8n_client:
        return jsonify({"error": "n8n integration not configured"}), 503

    data = request.json or {}
    workflow = data.get("workflow", "").strip()
    workflow_data = data.get("data", {})

    valid_workflows = ["onboarding", "offboarding", "weekly_feedback", "health_check"]
    if workflow not in valid_workflows:
        return jsonify({
            "error": f"Invalid workflow. Must be one of: {', '.join(valid_workflows)}"
        }), 400

    try:
        # Trigger the appropriate workflow
        if workflow == "onboarding":
            result = current_app.n8n_client.trigger_onboarding(workflow_data)
        elif workflow == "offboarding":
            result = current_app.n8n_client.trigger_offboarding(workflow_data)
        elif workflow == "weekly_feedback":
            result = current_app.n8n_client.trigger_weekly_feedback(workflow_data)
        elif workflow == "health_check":
            result = current_app.n8n_client.trigger_health_check(workflow_data)

        current_app.logger.info(f"[{g.request_id}] Triggered workflow: {workflow}")
        return jsonify({
            "status": "triggered",
            "workflow": workflow,
            "execution_id": result.get("execution_id")
        })
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Workflow trigger error: {e}", exc_info=True)
        return jsonify({"error": f"Failed to trigger workflow: {str(e)}"}), 500


def _get_workflow_repository():
    """Get WorkflowRepository from app context."""
    if hasattr(current_app, 'workflow_repository') and current_app.workflow_repository:
        return current_app.workflow_repository
    from ..repositories import WorkflowRepository
    return WorkflowRepository(db_path=current_app.config["DB_PATH"])


def _get_meeting_repository():
    """Get MeetingRepository from app context."""
    if hasattr(current_app, 'meeting_repository') and current_app.meeting_repository:
        return current_app.meeting_repository
    from ..repositories import MeetingRepository
    return MeetingRepository(db_path=current_app.config["DB_PATH"])


@workflows_bp.route("/api/workflow/<execution_id>", methods=["GET"])
@require_api_auth
def get_workflow_status(execution_id: str):
    """Get the status of a workflow execution."""
    try:
        repo = _get_workflow_repository()
        execution = repo.get_by_id(execution_id)
        if execution:
            return jsonify(execution)
        return jsonify({"error": "Execution not found"}), 404
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Get workflow status error: {e}", exc_info=True)
        return jsonify({"error": "Failed to get status"}), 500


@workflows_bp.route("/api/workflow/recent", methods=["GET"])
@require_api_auth
def get_recent_workflows():
    """Get recent workflow executions."""
    limit = request.args.get("limit", 10, type=int)
    workflow_type = request.args.get("workflow")

    try:
        repo = _get_workflow_repository()
        executions = repo.get_recent(
            limit=min(limit, 100),
            workflow_type=workflow_type
        )
        return jsonify({"executions": executions, "count": len(executions)})
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Get recent workflows error: {e}", exc_info=True)
        return jsonify({"error": "Failed to get executions"}), 500


@workflows_bp.route("/api/workflow/weekly-report", methods=["POST"])
@require_api_auth
def execute_weekly_report():
    """
    Execute weekly issue report and send to Zoom channel.

    Called by n8n on schedule (e.g., Monday 9am).

    Uses the WorkflowOrchestrator to:
    1. Generate report from ReportService
    2. Enhance via QA Brain
    3. Deliver via ChannelManager

    JSON body (optional):
        channel_jid: Target Zoom channel JID (defaults to env var)
        force_refresh: Refresh cache before generating report
    """
    import os
    from ..channels import ChannelType

    data = request.json or {}
    channel_jid = data.get("channel_jid") or os.environ.get("WEEKLY_REPORT_CHANNEL_JID")

    if not channel_jid:
        return jsonify({
            "error": "No target channel configured. Set WEEKLY_REPORT_CHANNEL_JID or pass channel_jid"
        }), 400

    if not hasattr(current_app, 'workflow_orchestrator') or not current_app.workflow_orchestrator:
        return jsonify({"error": "Workflow orchestrator not configured"}), 503

    try:
        # Optional: refresh cache first
        if data.get("force_refresh") and current_app.issue_cache:
            current_app.logger.info(f"[{g.request_id}] Refreshing cache before report")
            current_app.issue_cache.refresh()

        # Execute workflow via orchestrator
        workflow_result = current_app.workflow_orchestrator.execute_weekly_report(
            channel=ChannelType.ZOOM,
            destination=channel_jid,
            force_refresh=False,  # Already refreshed above if requested
        )

        # Map WorkflowResult to legacy response format for API compatibility
        result = {
            "success": workflow_result.success and workflow_result.delivery_success,
            "warnings": workflow_result.warnings,
            "report": workflow_result.data,
            "message_sent": workflow_result.delivery_success,
        }

        if workflow_result.delivery_error:
            result["warnings"].append(workflow_result.delivery_error)

        current_app.logger.info(
            f"[{g.request_id}] Weekly report workflow: "
            f"success={result['success']}, sent={result['message_sent']}"
        )

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Weekly report error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e),
            "warnings": [],
            "report": None,
            "message_sent": False,
        }), 500


@workflows_bp.route("/api/workflow/hygiene-check", methods=["POST"])
@require_api_auth
def execute_hygiene_check():
    """
    Execute daily issue hygiene check and send alerts to Zoom channel.

    Called by n8n on schedule (e.g., daily at 8am).

    Uses the WorkflowOrchestrator to:
    1. Run hygiene check from HygieneService
    2. Enhance via QA Brain
    3. Deliver via ChannelManager

    JSON body (optional):
        channel_jid: Target Zoom channel JID (defaults to env var)
        force_refresh: Refresh cache before checking
    """
    import os
    from ..channels import ChannelType

    data = request.json or {}
    channel_jid = data.get("channel_jid") or os.environ.get("HYGIENE_ALERT_CHANNEL_JID")

    if not channel_jid:
        return jsonify({
            "error": "No target channel configured. Set HYGIENE_ALERT_CHANNEL_JID or pass channel_jid"
        }), 400

    if not hasattr(current_app, 'workflow_orchestrator') or not current_app.workflow_orchestrator:
        return jsonify({"error": "Workflow orchestrator not configured"}), 503

    try:
        # Optional: refresh cache first
        if data.get("force_refresh") and current_app.issue_cache:
            current_app.logger.info(f"[{g.request_id}] Refreshing cache before hygiene check")
            current_app.issue_cache.refresh()

        # Execute workflow via orchestrator
        workflow_result = current_app.workflow_orchestrator.execute_hygiene_check(
            channel=ChannelType.ZOOM,
            destination=channel_jid,
        )

        # Map WorkflowResult to legacy response format for API compatibility
        result = {
            "success": workflow_result.success and workflow_result.delivery_success,
            "warnings": workflow_result.warnings,
            "report": workflow_result.data,
            "message_sent": workflow_result.delivery_success,
        }

        if workflow_result.delivery_error:
            result["warnings"].append(workflow_result.delivery_error)

        current_app.logger.info(
            f"[{g.request_id}] Hygiene check workflow: "
            f"success={result['success']}, sent={result['message_sent']}"
        )

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Hygiene check error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e),
            "warnings": [],
            "report": None,
            "message_sent": False,
        }), 500


@workflows_bp.route("/api/workflow/feedback-reminder", methods=["POST"])
@require_api_auth
def execute_feedback_reminder():
    """
    Execute weekly intern feedback reminder and send to Zoom channel.

    Called by n8n on schedule (e.g., Friday 2pm).

    Uses the WorkflowOrchestrator to:
    1. Generate reminder from FeedbackService
    2. Enhance via QA Brain
    3. Deliver via ChannelManager

    JSON body (optional):
        channel_jid: Target Zoom channel JID (defaults to env var)
    """
    import os
    from ..channels import ChannelType

    data = request.json or {}
    channel_jid = data.get("channel_jid") or os.environ.get("FEEDBACK_REMINDER_CHANNEL_JID")

    if not channel_jid:
        return jsonify({
            "error": "No target channel configured. Set FEEDBACK_REMINDER_CHANNEL_JID or pass channel_jid"
        }), 400

    if not hasattr(current_app, 'workflow_orchestrator') or not current_app.workflow_orchestrator:
        return jsonify({"error": "Workflow orchestrator not configured"}), 503

    try:
        # Execute workflow via orchestrator
        workflow_result = current_app.workflow_orchestrator.execute_feedback_reminder(
            channel=ChannelType.ZOOM,
            destination=channel_jid,
        )

        # Map WorkflowResult to legacy response format for API compatibility
        result = {
            "success": workflow_result.success and workflow_result.delivery_success,
            "warnings": workflow_result.warnings,
            "reminder": workflow_result.data,
            "message_sent": workflow_result.delivery_success,
        }

        if workflow_result.delivery_error:
            result["warnings"].append(workflow_result.delivery_error)

        current_app.logger.info(
            f"[{g.request_id}] Feedback reminder workflow: "
            f"success={result['success']}, sent={result['message_sent']}"
        )

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Feedback reminder error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e),
            "warnings": [],
            "reminder": None,
            "message_sent": False,
        }), 500


@workflows_bp.route("/api/workflow/meeting-summary", methods=["POST"])
@require_api_auth
def execute_meeting_summary():
    """
    Generate and send meeting summary to Zoom channel.

    Can be called after meeting ends or triggered manually.

    JSON body:
        meeting_id: Meeting ID to summarize (required)
        channel_jid: Target Zoom channel JID (defaults to env var)
        meeting_name: Name/title of the meeting (optional)
    """
    import os
    import time

    data = request.json or {}
    meeting_id = data.get("meeting_id")

    if not meeting_id:
        return jsonify({"error": "meeting_id is required"}), 400

    channel_jid = data.get("channel_jid") or os.environ.get("MEETING_SUMMARY_CHANNEL_JID")

    if not channel_jid:
        return jsonify({
            "error": "No target channel configured. Set MEETING_SUMMARY_CHANNEL_JID or pass channel_jid"
        }), 400

    if not current_app.qa_brain:
        return jsonify({"error": "QA Brain not configured - cannot generate summary"}), 503

    result = {
        "success": False,
        "warnings": [],
        "summary": None,
        "message_sent": False,
    }

    try:
        # Get meeting transcript from database
        repo = _get_meeting_repository()
        transcript_data = repo.get_transcript(meeting_id)

        if not transcript_data or not transcript_data.get("transcript"):
            result["warnings"].append("No transcript found for meeting")
            return jsonify(result), 404

        # Get meeting metadata
        meeting_name = data.get("meeting_name") or transcript_data.get("meeting_name", "Team Meeting")
        meeting_date = transcript_data.get("meeting_date")
        duration = transcript_data.get("duration")
        participants = transcript_data.get("participants", [])

        # Generate summary
        summary = current_app.qa_brain.generate_meeting_summary(
            transcript=transcript_data["transcript"],
            meeting_name=meeting_name,
            meeting_date=meeting_date,
            duration=duration,
            participants=participants,
        )

        result["summary"] = summary

        # Format header for Zoom
        header = f"**Meeting Summary: {meeting_name}**\n"
        if meeting_date:
            header += f"*{meeting_date}*\n"
        header += "\n"

        full_message = header + summary

        # Send to Zoom with retry
        if current_app.zoom_chatbot:
            for attempt in range(3):
                try:
                    current_app.zoom_chatbot.send_message(
                        message=full_message,
                        to_jid=channel_jid,
                        account_id=current_app.config.get("ZOOM_ACCOUNT_ID", ""),
                    )
                    result["message_sent"] = True
                    result["success"] = True
                    current_app.logger.info(f"[{g.request_id}] Meeting summary sent to {channel_jid}")
                    break
                except Exception as e:
                    current_app.logger.warning(f"[{g.request_id}] Zoom send attempt {attempt+1} failed: {e}")
                    if attempt < 2:
                        time.sleep(2 ** attempt)

            if not result["message_sent"]:
                result["warnings"].append("Failed to send to Zoom after 3 attempts")
        else:
            result["warnings"].append("Zoom chatbot not configured")
            result["success"] = True  # Summary generated successfully

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] Meeting summary error: {e}", exc_info=True)
        result["error"] = str(e)
        return jsonify(result), 500


@workflows_bp.route("/n8n/callback", methods=["POST"])
def n8n_callback():
    """
    Receive callbacks from n8n workflows.

    JSON body:
        execution_id: The execution ID from the trigger response
        status: Workflow status (completed, failed, etc.)
        result: Workflow result data (optional)
        secret: Callback secret for authentication
    """
    import hmac

    data = request.json or {}

    # Verify callback secret using constant-time comparison (Council fix B1)
    # Callback secret is REQUIRED for security - reject if not configured (Council fix B2)
    callback_secret = current_app.config.get("N8N_CALLBACK_SECRET")
    if not callback_secret:
        current_app.logger.error(f"[{g.request_id}] n8n callback rejected - N8N_CALLBACK_SECRET not configured")
        return jsonify({"error": "Callback authentication not configured"}), 503

    provided_secret = data.get("secret") or request.headers.get("X-Callback-Secret") or ""

    if not hmac.compare_digest(provided_secret, callback_secret):
        current_app.logger.warning(f"[{g.request_id}] n8n callback with invalid secret")
        return jsonify({"error": "Invalid callback secret"}), 401

    execution_id = data.get("execution_id")
    status = data.get("status")

    if not execution_id or not status:
        return jsonify({"error": "execution_id and status are required"}), 400

    try:
        repo = _get_workflow_repository()
        repo.update_status(
            execution_id=execution_id,
            status=status,
            result=data.get("result")
        )
        current_app.logger.info(f"[{g.request_id}] n8n callback: {execution_id} -> {status}")
        return jsonify({"status": "recorded"})
    except Exception as e:
        current_app.logger.error(f"[{g.request_id}] n8n callback error: {e}", exc_info=True)
        return jsonify({"error": "Failed to record callback"}), 500
