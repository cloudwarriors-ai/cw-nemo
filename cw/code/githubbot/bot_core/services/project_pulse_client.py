"""
Project Pulse API client.

Provides methods to communicate with Project Pulse for:
- Creating tickets from Zoom issues
- Updating ticket status from GitHub webhooks
"""
import os
import logging
from typing import Optional, Dict, Any

import requests

from .status_mapper import ProjectPulseStatus

logger = logging.getLogger(__name__)


class ProjectPulseClient:
    """
    API client for Project Pulse integration.

    Handles:
    - Creating support tickets from Zoom-created issues
    - Updating ticket status when GitHub issues change
    """

    def __init__(self):
        self.api_url = os.environ.get('PROJECT_PULSE_API_URL', '')
        self.api_secret = os.environ.get('PROJECT_PULSE_API_SECRET', '')

        # Log configuration status
        logger.info("Initializing Project Pulse Client")
        logger.info(f"- API URL: {'✓ Present' if self.api_url else '✗ Missing'}")
        logger.info(f"- API Secret: {'✓ Present' if self.api_secret else '✗ Missing'}")

        self.enabled = bool(self.api_url and self.api_secret)
        if not self.enabled:
            logger.warning("Project Pulse Client is disabled - missing configuration")

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            'Content-Type': 'application/json',
            'X-API-Key': self.api_secret,
        }

    def create_ticket(
        self,
        title: str,
        description: str,
        github_repo: str,
        github_issue_number: int,
        github_issue_url: str,
        application_name: str,
        source: str = 'ZoomChat',
        submitter_name: str = 'Zoom User'
    ) -> Optional[Dict[str, Any]]:
        """
        Create a support ticket in Project Pulse.

        Called when an issue is created via Zoom to sync it to Project Pulse.

        Args:
            title: Issue title
            description: Issue description
            github_repo: GitHub repository (e.g., "org/repo")
            github_issue_number: GitHub issue number
            github_issue_url: GitHub issue URL
            application_name: Name of the application
            source: Source of the ticket ('ZoomChat' or 'ProjectPulse')
            submitter_name: Name of the person who submitted

        Returns:
            Response data dict with ticket_id, or None on failure
        """
        if not self.enabled:
            logger.warning("Project Pulse Client is not enabled - skipping ticket creation")
            return None

        endpoint = f"{self.api_url}/support-tickets/from-external"

        payload = {
            'title': title,
            'description': description,
            'githubRepo': github_repo,
            'githubIssueNumber': github_issue_number,
            'githubIssueUrl': github_issue_url,
            'applicationName': application_name,
            'source': source,
            'submitterName': submitter_name,
        }

        try:
            logger.info(f"Creating Project Pulse ticket for GitHub issue #{github_issue_number}")
            logger.debug(f"Payload: {payload}")

            response = requests.post(
                endpoint,
                headers=self._get_headers(),
                json=payload,
                timeout=10
            )

            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response body: {response.text}")

            if response.status_code in [200, 201]:
                data = response.json()
                logger.info(f"Successfully created Project Pulse ticket: {data.get('ticketId', 'unknown')}")
                return data
            else:
                logger.error(f"Failed to create Project Pulse ticket: {response.status_code} - {response.text}")
                return None

        except requests.exceptions.Timeout:
            logger.error("Project Pulse API request timed out")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Project Pulse API request failed: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating Project Pulse ticket: {str(e)}", exc_info=True)
            return None

    def update_ticket_status(
        self,
        ticket_id: str,
        new_status: ProjectPulseStatus,
        github_event_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update a ticket's status in Project Pulse.

        Called when a GitHub webhook indicates a status change.

        Args:
            ticket_id: Project Pulse ticket ID
            new_status: New status to set
            github_event_data: Optional GitHub event data for context

        Returns:
            True if update was successful, False otherwise
        """
        if not self.enabled:
            logger.warning("Project Pulse Client is not enabled - skipping status update")
            return False

        endpoint = f"{self.api_url}/webhooks/github-status"

        payload = {
            'ticketId': ticket_id,
            'newStatus': new_status.value,
        }

        if github_event_data:
            payload['githubEventData'] = {
                'action': github_event_data.get('action'),
                'actor': github_event_data.get('actor'),
                'labels': github_event_data.get('labels', []),
                'assignees': github_event_data.get('assignees', []),
            }

        try:
            logger.info(f"Updating Project Pulse ticket {ticket_id} status to {new_status.value}")
            logger.debug(f"Payload: {payload}")

            response = requests.post(
                endpoint,
                headers=self._get_headers(),
                json=payload,
                timeout=10
            )

            logger.debug(f"Response status: {response.status_code}")

            if response.status_code in [200, 204]:
                logger.info(f"Successfully updated Project Pulse ticket {ticket_id}")
                return True
            else:
                logger.error(f"Failed to update Project Pulse ticket: {response.status_code} - {response.text}")
                return False

        except requests.exceptions.Timeout:
            logger.error("Project Pulse API request timed out")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Project Pulse API request failed: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error updating Project Pulse ticket: {str(e)}", exc_info=True)
            return False

    def get_ticket_by_github_issue(
        self,
        github_repo: str,
        github_issue_number: int
    ) -> Optional[Dict[str, Any]]:
        """
        Look up a Project Pulse ticket by GitHub issue reference.

        Args:
            github_repo: GitHub repository (e.g., "org/repo")
            github_issue_number: GitHub issue number

        Returns:
            Ticket data dict or None if not found
        """
        if not self.enabled:
            logger.warning("Project Pulse Client is not enabled")
            return None

        # URL encode the repo path
        repo_encoded = github_repo.replace('/', '%2F')
        endpoint = f"{self.api_url}/support-tickets/by-github/{repo_encoded}/{github_issue_number}"

        try:
            logger.debug(f"Looking up Project Pulse ticket for {github_repo}#{github_issue_number}")

            response = requests.get(
                endpoint,
                headers=self._get_headers(),
                timeout=10
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logger.debug(f"No Project Pulse ticket found for {github_repo}#{github_issue_number}")
                return None
            else:
                logger.error(f"Failed to look up ticket: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error looking up Project Pulse ticket: {str(e)}")
            return None


# Initialize the client singleton
logger.info("Attempting to initialize Project Pulse client")
try:
    project_pulse_client = ProjectPulseClient()
    logger.info("Project Pulse client initialized successfully")
except Exception as e:
    logger.error("Failed to initialize Project Pulse client", exc_info=True)
    project_pulse_client = None
