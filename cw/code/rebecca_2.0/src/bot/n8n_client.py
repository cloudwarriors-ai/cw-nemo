"""
n8n workflow client for triggering and managing automated workflows.

Handles onboarding, offboarding, weekly feedback, and health check workflows.
Protected by circuit breaker for resilience against n8n outages.
"""
import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

import requests

from .circuit_breaker import get_circuit_breaker, CircuitOpenError
from .errors import sanitize_response_text


class WorkflowType(Enum):
    """Types of workflows that can be triggered."""
    ONBOARDING = "onboarding"
    OFFBOARDING = "offboarding"
    WEEKLY_FEEDBACK = "weekly_feedback"
    HEALTH_CHECK = "health_check"
    REPORT_UPLOAD = "report_upload"
    CUSTOM = "custom"


class WorkflowStatus(Enum):
    """Status of a workflow execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class N8nClient:
    """
    Client for triggering n8n workflows via webhooks.

    Each workflow type has a configurable webhook URL. The client tracks
    workflow executions in the database for monitoring and debugging.
    """

    def __init__(
        self,
        webhook_base_url: str,
        db_path: str = "data/state.db",
        timeout_seconds: int = 30,
        logger: logging.Logger = None
    ):
        """
        Initialize the n8n client.

        Args:
            webhook_base_url: Base URL for n8n webhooks (e.g., https://n8n.example.com/webhook)
            db_path: Path to SQLite database
            timeout_seconds: Request timeout
            logger: Logger instance
        """
        self.webhook_base_url = webhook_base_url.rstrip("/")
        self.db_path = db_path
        self.timeout = timeout_seconds
        self.logger = logger or logging.getLogger("qa_agent")

        # Circuit breaker for n8n API resilience
        self._circuit_breaker = get_circuit_breaker(
            name="n8n",
            failure_threshold=5,
            recovery_timeout=60,
            logger=self.logger,
        )

        # Workflow-specific webhook paths
        self.workflow_paths = {
            WorkflowType.ONBOARDING: "/onboarding",
            WorkflowType.OFFBOARDING: "/offboarding",
            WorkflowType.WEEKLY_FEEDBACK: "/weekly-feedback",
            WorkflowType.HEALTH_CHECK: "/health-check",
            WorkflowType.REPORT_UPLOAD: "/report-upload",
        }

    def trigger_onboarding(
        self,
        intern_name: str,
        intern_email: Optional[str] = None,
        github_username: Optional[str] = None,
        program: Optional[str] = None,
        start_date: Optional[str] = None,
        supervisor: Optional[str] = None,
        zoom_meeting_ids: Optional[list[str]] = None,
        intern_id: Optional[str] = None,
    ) -> dict:
        """
        Trigger the intern onboarding workflow.

        This workflow will:
        - Send welcome email to intern
        - Add intern to Zoom meetings
        - Send GitHub org invitation (handled separately)
        - Schedule orientation checklist (delayed 24hrs)
        - Set up weekly progress reminders

        Args:
            intern_name: Intern's display name
            intern_email: Intern's email address
            github_username: GitHub username for org invite
            program: Program type (skillbridge, vanderbilt, other)
            start_date: Start date (YYYY-MM-DD)
            supervisor: Supervisor's name
            zoom_meeting_ids: List of Zoom meeting IDs to add intern to
            intern_id: Unique intern identifier (optional, auto-generated if not provided)

        Returns:
            dict with execution_id and status
        """
        payload = {
            "intern_id": intern_id or str(uuid.uuid4())[:8],
            "intern_name": intern_name,
            "intern_email": intern_email,
            "github_username": github_username,
            "program": program,
            "start_date": start_date,
            "supervisor": supervisor,
            "zoom_meeting_ids": zoom_meeting_ids or [],
            "triggered_at": datetime.now().isoformat(),
        }

        return self._trigger_workflow(
            workflow_type=WorkflowType.ONBOARDING,
            payload=payload,
            context={"intern_name": intern_name, "program": program}
        )

    def trigger_offboarding(
        self,
        intern_name: str,
        intern_email: Optional[str] = None,
        github_username: Optional[str] = None,
        exit_survey_url: Optional[str] = None,
        intern_id: Optional[str] = None,
        end_date: Optional[str] = None,
        reason: str = "internship_complete"
    ) -> dict:
        """
        Trigger the intern offboarding workflow.

        This workflow will:
        - Send farewell email to intern
        - Share exit survey link
        - Remove from GitHub org (handled separately)
        - Notify supervisor
        - Archive documents

        Args:
            intern_name: Intern's display name
            intern_email: Intern's email address
            github_username: GitHub username for org removal
            exit_survey_url: URL to exit survey form
            intern_id: Unique intern identifier
            end_date: End date (YYYY-MM-DD)
            reason: Reason for offboarding

        Returns:
            dict with execution_id and status
        """
        payload = {
            "intern_id": intern_id,
            "intern_name": intern_name,
            "intern_email": intern_email,
            "github_username": github_username,
            "exit_survey_url": exit_survey_url,
            "end_date": end_date or datetime.now().strftime("%Y-%m-%d"),
            "reason": reason,
            "triggered_at": datetime.now().isoformat(),
        }

        return self._trigger_workflow(
            workflow_type=WorkflowType.OFFBOARDING,
            payload=payload,
            context={"intern_name": intern_name}
        )

    def trigger_weekly_feedback(
        self,
        intern_id: str,
        intern_name: str,
        supervisor: str,
        week_ending: str
    ) -> dict:
        """
        Trigger the weekly feedback preparation workflow.

        This workflow will:
        - Query GitHub for intern's closed issues this week
        - Query state DB for completed tasks
        - Compile summary document
        - Send to Zoom channel for supervisor review

        Args:
            intern_id: Unique intern identifier
            intern_name: Intern's display name
            supervisor: Supervisor to notify
            week_ending: Friday date (YYYY-MM-DD)

        Returns:
            dict with execution_id and status
        """
        payload = {
            "intern_id": intern_id,
            "intern_name": intern_name,
            "supervisor": supervisor,
            "week_ending": week_ending,
            "triggered_at": datetime.now().isoformat(),
        }

        return self._trigger_workflow(
            workflow_type=WorkflowType.WEEKLY_FEEDBACK,
            payload=payload,
            context={"intern_id": intern_id, "week": week_ending}
        )

    def trigger_health_check(
        self,
        applications: list[str],
        notify_channel: str = "devops"
    ) -> dict:
        """
        Trigger the application health check workflow.

        This workflow will:
        - Run health check scripts for each application
        - Compile results
        - Post to Zoom DevOps channel
        - Create GitHub issues for failures

        Args:
            applications: List of application names to check
            notify_channel: Zoom channel for notifications

        Returns:
            dict with execution_id and status
        """
        payload = {
            "applications": applications,
            "notify_channel": notify_channel,
            "triggered_at": datetime.now().isoformat(),
        }

        return self._trigger_workflow(
            workflow_type=WorkflowType.HEALTH_CHECK,
            payload=payload,
            context={"apps": ",".join(applications)}
        )

    def trigger_report_upload(
        self,
        file_base64: str,
        filename: str,
        folder_id: str = None,
        report_type: str = "weekly_issues"
    ) -> dict:
        """
        Trigger the report upload workflow to upload file to Google Drive.

        This workflow will:
        - Decode the base64 file
        - Upload to Google Drive folder
        - Return shareable link

        IMPORTANT: This is a synchronous call - it waits for the n8n workflow
        to complete and return the Google Drive link.

        Args:
            file_base64: Base64-encoded file content
            filename: Name for the file (e.g., "Github_Issues_20260113.xlsx")
            folder_id: Google Drive folder ID (optional, uses default if not provided)
            report_type: Type of report for logging

        Returns:
            dict with execution_id, status, and drive_link (if successful)
        """
        payload = {
            "file_base64": file_base64,
            "filename": filename,
            "folder_id": folder_id,
            "report_type": report_type,
            "triggered_at": datetime.now().isoformat(),
        }

        # Use a longer timeout for sync upload
        original_timeout = self.timeout
        self.timeout = 60  # Allow more time for upload

        try:
            result = self._trigger_workflow_sync(
                workflow_type=WorkflowType.REPORT_UPLOAD,
                payload=payload,
                context={"filename": filename, "report_type": report_type}
            )
            return result
        finally:
            self.timeout = original_timeout

    def _trigger_workflow_sync(
        self,
        workflow_type: WorkflowType,
        payload: dict,
        context: dict,
    ) -> dict:
        """
        Trigger a workflow and wait for the response (synchronous).

        Unlike _trigger_workflow, this waits for the n8n workflow to complete
        and returns its response. Used for workflows that need to return data.
        Protected by circuit breaker to prevent cascading failures.

        Args:
            workflow_type: Type of workflow
            payload: Data to send
            context: Context for logging

        Returns:
            dict with execution_id, status, and response data
        """
        # Check circuit breaker before attempting workflow
        if not self._circuit_breaker.can_execute():
            return {
                "execution_id": None,
                "status": "circuit_open",
                "error": "n8n service temporarily unavailable (circuit breaker open)"
            }

        execution_id = str(uuid.uuid4())[:12]
        path = self.workflow_paths.get(workflow_type, "")
        webhook_url = f"{self.webhook_base_url}{path}"

        payload["execution_id"] = execution_id

        self._store_execution(
            execution_id=execution_id,
            workflow_type=workflow_type.value,
            payload={k: v for k, v in payload.items() if k != "file_base64"},  # Don't store file
            context=context
        )

        try:
            self.logger.info(f"Triggering sync {workflow_type.value} workflow: {execution_id}")

            response = requests.post(
                webhook_url,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code in (200, 201):
                try:
                    response_data = response.json()
                except Exception:
                    # SECURITY: Sanitize raw response text to prevent secret leakage
                    response_data = {"raw": sanitize_response_text(response.text, max_length=500)}

                self._circuit_breaker.record_success()
                self._update_execution_status(
                    execution_id=execution_id,
                    status=WorkflowStatus.COMPLETED,
                    result=response_data
                )

                return {
                    "execution_id": execution_id,
                    "status": "completed",
                    "workflow_type": workflow_type.value,
                    "drive_link": response_data.get("webViewLink") or response_data.get("drive_link"),
                    "file_id": response_data.get("id") or response_data.get("file_id"),
                    "response": response_data
                }
            else:
                # SECURITY: Sanitize error response to prevent secret leakage
                error_msg = f"HTTP {response.status_code}: {sanitize_response_text(response.text)}"
                self._circuit_breaker.record_failure()
                self._update_execution_status(
                    execution_id=execution_id,
                    status=WorkflowStatus.FAILED,
                    error=error_msg
                )
                self.logger.error(f"Sync workflow failed: {error_msg}")
                return {
                    "execution_id": execution_id,
                    "status": "failed",
                    "error": error_msg
                }

        except requests.Timeout:
            error_msg = "Request timed out waiting for n8n response"
            self._circuit_breaker.record_failure()
            self._update_execution_status(
                execution_id=execution_id,
                status=WorkflowStatus.FAILED,
                error=error_msg
            )
            self.logger.error(f"Sync workflow timed out: {execution_id}")
            return {
                "execution_id": execution_id,
                "status": "failed",
                "error": error_msg
            }

        except requests.RequestException as e:
            error_msg = str(e)
            self._circuit_breaker.record_failure()
            self._update_execution_status(
                execution_id=execution_id,
                status=WorkflowStatus.FAILED,
                error=error_msg
            )
            self.logger.error(f"Sync workflow error: {error_msg}")
            return {
                "execution_id": execution_id,
                "status": "failed",
                "error": error_msg
            }

    def trigger_custom(
        self,
        webhook_path: str,
        payload: dict
    ) -> dict:
        """
        Trigger a custom workflow by webhook path.

        Args:
            webhook_path: Path to append to base URL
            payload: Data to send to workflow

        Returns:
            dict with execution_id and status
        """
        return self._trigger_workflow(
            workflow_type=WorkflowType.CUSTOM,
            payload=payload,
            context={"path": webhook_path},
            custom_path=webhook_path
        )

    def trigger_workflow(
        self,
        workflow_type: WorkflowType,
        payload: dict,
        context: dict = None,
        custom_path: str = None,
        max_retries: int = 3
    ) -> dict:
        """Public alias for _trigger_workflow for backward compatibility."""
        return self._trigger_workflow(
            workflow_type=workflow_type,
            payload=payload,
            context=context or {},
            custom_path=custom_path,
            max_retries=max_retries
        )

    def _trigger_workflow(
        self,
        workflow_type: WorkflowType,
        payload: dict,
        context: dict,
        custom_path: str = None,
        max_retries: int = 3
    ) -> dict:
        """
        Internal method to trigger a workflow and track execution.

        Uses exponential backoff for transient failures.
        Protected by circuit breaker to prevent cascading failures.

        Args:
            workflow_type: Type of workflow
            payload: Data to send
            context: Context for logging
            custom_path: Custom webhook path (for CUSTOM type)
            max_retries: Maximum retry attempts for transient failures

        Returns:
            dict with execution_id, status, and any error
        """
        # Check circuit breaker before attempting workflow
        if not self._circuit_breaker.can_execute():
            return {
                "execution_id": None,
                "status": "circuit_open",
                "error": "n8n service temporarily unavailable (circuit breaker open)"
            }

        execution_id = str(uuid.uuid4())[:12]

        # Determine webhook URL
        if custom_path:
            webhook_url = f"{self.webhook_base_url}{custom_path}"
        else:
            path = self.workflow_paths.get(workflow_type, "")
            webhook_url = f"{self.webhook_base_url}{path}"

        # Add execution ID to payload for tracking
        payload["execution_id"] = execution_id

        # Store execution record
        self._store_execution(
            execution_id=execution_id,
            workflow_type=workflow_type.value,
            payload=payload,
            context=context
        )

        # Trigger the workflow with retry logic
        last_error = None
        for attempt in range(max_retries):
            try:
                self.logger.info(
                    f"Triggering {workflow_type.value} workflow: {execution_id}"
                    + (f" (attempt {attempt + 1})" if attempt > 0 else "")
                )

                response = requests.post(
                    webhook_url,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"}
                )

                if response.status_code in (200, 201, 202):
                    self._circuit_breaker.record_success()
                    self._update_execution_status(
                        execution_id=execution_id,
                        status=WorkflowStatus.RUNNING
                    )
                    return {
                        "execution_id": execution_id,
                        "status": "triggered",
                        "workflow_type": workflow_type.value
                    }
                elif response.status_code >= 500:
                    # Server error - retry
                    # SECURITY: Sanitize error response to prevent secret leakage
                    last_error = f"HTTP {response.status_code}: {sanitize_response_text(response.text)}"
                    self.logger.warning(f"Workflow trigger server error (attempt {attempt + 1}): {last_error}")
                else:
                    # Client error - don't retry
                    # SECURITY: Sanitize error response to prevent secret leakage
                    error_msg = f"HTTP {response.status_code}: {sanitize_response_text(response.text)}"
                    self._update_execution_status(
                        execution_id=execution_id,
                        status=WorkflowStatus.FAILED,
                        error=error_msg
                    )
                    self.logger.error(f"Workflow trigger failed: {error_msg}")
                    return {
                        "execution_id": execution_id,
                        "status": "failed",
                        "error": error_msg
                    }

            except (requests.Timeout, requests.ConnectionError) as e:
                # Transient error - retry
                last_error = str(e)
                self.logger.warning(f"Workflow trigger transient error (attempt {attempt + 1}): {last_error}")

            except requests.RequestException as e:
                # Other request error - don't retry
                error_msg = str(e)
                self._circuit_breaker.record_failure()
                self._update_execution_status(
                    execution_id=execution_id,
                    status=WorkflowStatus.FAILED,
                    error=error_msg
                )
                self.logger.error(f"Workflow trigger error: {error_msg}")
                return {
                    "execution_id": execution_id,
                    "status": "failed",
                    "error": error_msg
                }

            # Exponential backoff before retry
            if attempt < max_retries - 1:
                sleep_time = (2 ** attempt) * 0.5  # 0.5s, 1s, 2s
                time.sleep(sleep_time)

        # All retries exhausted - record failure
        self._circuit_breaker.record_failure()
        error_msg = f"Failed after {max_retries} attempts: {last_error}"
        self._update_execution_status(
            execution_id=execution_id,
            status=WorkflowStatus.FAILED,
            error=error_msg
        )
        self.logger.error(f"Workflow trigger exhausted retries: {execution_id}")
        return {
            "execution_id": execution_id,
            "status": "failed",
            "error": error_msg
        }

    def get_execution_status(self, execution_id: str) -> Optional[dict]:
        """
        Get the status of a workflow execution.

        Args:
            execution_id: Execution ID to look up

        Returns:
            dict with execution details or None if not found
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM workflow_executions
                WHERE id = ?
            """, (execution_id,))

            row = cursor.fetchone()
            conn.close()

            if row:
                return dict(row)
            return None

        except Exception as e:
            self.logger.warning(f"Failed to get execution status: {e}")
            return None

    def get_recent_executions(
        self,
        workflow_type: str = None,
        limit: int = 20
    ) -> list[dict]:
        """
        Get recent workflow executions.

        Args:
            workflow_type: Filter by type (optional)
            limit: Maximum number of results

        Returns:
            List of execution records
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if workflow_type:
                cursor.execute("""
                    SELECT * FROM workflow_executions
                    WHERE workflow_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (workflow_type, limit))
            else:
                cursor.execute("""
                    SELECT * FROM workflow_executions
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))

            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results

        except Exception as e:
            self.logger.warning(f"Failed to get recent executions: {e}")
            return []

    def mark_completed(self, execution_id: str, result: dict = None) -> bool:
        """
        Mark a workflow execution as completed.

        Called by webhook callback from n8n when workflow finishes.

        Args:
            execution_id: Execution ID
            result: Optional result data from workflow

        Returns:
            True if updated, False otherwise
        """
        return self._update_execution_status(
            execution_id=execution_id,
            status=WorkflowStatus.COMPLETED,
            result=result
        )

    def mark_failed(self, execution_id: str, error: str) -> bool:
        """
        Mark a workflow execution as failed.

        Called by webhook callback from n8n when workflow fails.

        Args:
            execution_id: Execution ID
            error: Error message

        Returns:
            True if updated, False otherwise
        """
        return self._update_execution_status(
            execution_id=execution_id,
            status=WorkflowStatus.FAILED,
            error=error
        )

    def _store_execution(
        self,
        execution_id: str,
        workflow_type: str,
        payload: dict,
        context: dict
    ) -> None:
        """Store a new workflow execution record."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO workflow_executions
                (id, workflow_type, status, payload, context, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                execution_id,
                workflow_type,
                WorkflowStatus.PENDING.value,
                json.dumps(payload),
                json.dumps(context),
                datetime.now().isoformat()
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            self.logger.warning(f"Failed to store execution: {e}")

    def _update_execution_status(
        self,
        execution_id: str,
        status: WorkflowStatus,
        error: str = None,
        result: dict = None
    ) -> bool:
        """Update the status of a workflow execution."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if status == WorkflowStatus.COMPLETED:
                cursor.execute("""
                    UPDATE workflow_executions
                    SET status = ?, completed_at = ?, result = ?
                    WHERE id = ?
                """, (status.value, datetime.now().isoformat(), json.dumps(result) if result else None, execution_id))
            elif status == WorkflowStatus.FAILED:
                cursor.execute("""
                    UPDATE workflow_executions
                    SET status = ?, completed_at = ?, error = ?
                    WHERE id = ?
                """, (status.value, datetime.now().isoformat(), error, execution_id))
            else:
                cursor.execute("""
                    UPDATE workflow_executions
                    SET status = ?
                    WHERE id = ?
                """, (status.value, execution_id))

            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return success

        except Exception as e:
            self.logger.warning(f"Failed to update execution status: {e}")
            return False

    def get_circuit_status(self) -> dict:
        """Get circuit breaker status for health checks."""
        return self._circuit_breaker.get_status()
