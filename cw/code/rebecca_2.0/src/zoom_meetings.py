"""
Zoom Meetings API client for managing meeting registrations.

Used during onboarding to add interns to recurring meetings.
"""
import base64
import logging
import time
from typing import Optional

import requests


class ZoomMeetingsClient:
    """
    Client for Zoom Meetings API.

    Handles OAuth authentication and meeting registration for adding
    users to recurring meetings during onboarding.
    """

    TOKEN_URL = "https://zoom.us/oauth/token"
    API_BASE = "https://api.zoom.us/v2"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        account_id: str = None,
        logger: logging.Logger = None
    ):
        """
        Initialize Zoom Meetings client.

        Args:
            client_id: Zoom OAuth Client ID
            client_secret: Zoom OAuth Client Secret
            account_id: Zoom Account ID (for Server-to-Server OAuth)
            logger: Logger instance
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.account_id = account_id
        self.logger = logger or logging.getLogger("qa_agent")

        # Token cache
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0

    @staticmethod
    def _clean_meeting_id(meeting_id: str) -> str:
        """Remove spaces and dashes from meeting ID."""
        return meeting_id.replace(" ", "").replace("-", "")

    def _get_access_token(self) -> str:
        """Get OAuth access token using Server-to-Server OAuth."""
        # Return cached token if still valid
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        try:
            # Server-to-Server OAuth uses account_credentials grant
            response = requests.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={
                    "grant_type": "account_credentials",
                    "account_id": self.account_id
                },
                timeout=10
            )

            if response.status_code != 200:
                self.logger.error(f"Token request failed: {response.status_code} - {response.text}")
                response.raise_for_status()

            data = response.json()
            self._access_token = data["access_token"]
            self._token_expiry = time.time() + data.get("expires_in", 3600)

            self.logger.debug("Obtained new Zoom access token for Meetings API")
            return self._access_token

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to get Zoom access token: {e}")
            raise

    def add_meeting_registrant(
        self,
        meeting_id: str,
        email: str,
        first_name: str,
        last_name: str = "",
        auto_approve: bool = True
    ) -> dict:
        """
        Add a registrant to a meeting.

        For recurring meetings with registration enabled, this adds the user
        as a registrant so they receive meeting invites.

        Args:
            meeting_id: Zoom meeting ID (numbers only)
            email: Registrant's email address
            first_name: Registrant's first name
            last_name: Registrant's last name (optional)
            auto_approve: Whether to auto-approve the registration

        Returns:
            dict with success status and details
        """
        meeting_id = self._clean_meeting_id(meeting_id)

        try:
            token = self._get_access_token()

            payload = {
                "email": email,
                "first_name": first_name,
                "last_name": last_name or "",
                "auto_approve": auto_approve
            }

            response = requests.post(
                f"{self.API_BASE}/meetings/{meeting_id}/registrants",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10
            )

            if response.status_code in (200, 201):
                data = response.json()
                self.logger.info(f"Added registrant {email} to meeting {meeting_id}")
                return {
                    "success": True,
                    "registrant_id": data.get("registrant_id"),
                    "join_url": data.get("join_url"),
                    "status": data.get("status", "approved")
                }
            elif response.status_code == 400:
                # Check if already registered
                error_data = response.json()
                if "already registered" in str(error_data).lower():
                    self.logger.info(f"{email} already registered for meeting {meeting_id}")
                    return {
                        "success": True,
                        "status": "already_registered",
                        "message": "User already registered for this meeting"
                    }
                self.logger.warning(f"Registration failed: {response.text}")
                return {
                    "success": False,
                    "error": error_data.get("message", "Registration failed")
                }
            elif response.status_code == 404:
                self.logger.warning(f"Meeting {meeting_id} not found or registration not enabled")
                return {
                    "success": False,
                    "error": "Meeting not found or registration not enabled"
                }
            else:
                self.logger.error(f"Registration failed: {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}"
                }

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error adding meeting registrant: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def add_to_multiple_meetings(
        self,
        meeting_ids: list[str],
        email: str,
        first_name: str,
        last_name: str = ""
    ) -> dict:
        """
        Add a user to multiple recurring meetings.

        Used during onboarding to add intern to all required meetings.

        Args:
            meeting_ids: List of Zoom meeting IDs
            email: User's email address
            first_name: User's first name
            last_name: User's last name

        Returns:
            dict with success status and per-meeting results
        """
        results = {
            "success": True,
            "meetings": [],
            "errors": []
        }

        for meeting_id in meeting_ids:
            result = self.add_meeting_registrant(
                meeting_id=meeting_id,
                email=email,
                first_name=first_name,
                last_name=last_name
            )

            if result.get("success"):
                results["meetings"].append({
                    "meeting_id": meeting_id,
                    "status": result.get("status", "registered"),
                    "join_url": result.get("join_url")
                })
            else:
                results["errors"].append({
                    "meeting_id": meeting_id,
                    "error": result.get("error")
                })
                results["success"] = False

        return results

    def get_meeting_registrants(self, meeting_id: str) -> dict:
        """
        Get list of registrants for a meeting.

        Args:
            meeting_id: Zoom meeting ID

        Returns:
            dict with registrant list
        """
        meeting_id = self._clean_meeting_id(meeting_id)

        try:
            token = self._get_access_token()

            response = requests.get(
                f"{self.API_BASE}/meetings/{meeting_id}/registrants",
                headers={
                    "Authorization": f"Bearer {token}",
                },
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "registrants": data.get("registrants", []),
                    "total_records": data.get("total_records", 0)
                }
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}"
                }

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error getting meeting registrants: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def remove_meeting_registrant(
        self,
        meeting_id: str,
        registrant_id: str
    ) -> dict:
        """
        Remove a registrant from a meeting.

        Used during offboarding to remove intern from meetings.

        Args:
            meeting_id: Zoom meeting ID
            registrant_id: Registrant ID to remove

        Returns:
            dict with success status
        """
        meeting_id = self._clean_meeting_id(meeting_id)

        try:
            token = self._get_access_token()

            response = requests.delete(
                f"{self.API_BASE}/meetings/{meeting_id}/registrants/{registrant_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                },
                timeout=10
            )

            if response.status_code in (200, 204):
                self.logger.info(f"Removed registrant {registrant_id} from meeting {meeting_id}")
                return {"success": True}
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}"
                }

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error removing meeting registrant: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def remove_registrant_by_email(
        self,
        meeting_id: str,
        email: str
    ) -> dict:
        """
        Remove a registrant from a meeting by their email address.

        Looks up the registrant ID by email, then removes them.

        Args:
            meeting_id: Zoom meeting ID
            email: Email address of registrant to remove

        Returns:
            dict with success status
        """
        # First get all registrants to find the ID
        registrants_result = self.get_meeting_registrants(meeting_id)
        if not registrants_result.get("success"):
            return {
                "success": False,
                "error": f"Could not get registrants: {registrants_result.get('error')}"
            }

        # Find registrant by email
        registrant_id = None
        for reg in registrants_result.get("registrants", []):
            if reg.get("email", "").lower() == email.lower():
                registrant_id = reg.get("id")
                break

        if not registrant_id:
            self.logger.info(f"{email} not found as registrant for meeting {meeting_id}")
            return {
                "success": True,
                "status": "not_found",
                "message": "User not registered for this meeting"
            }

        # Remove the registrant
        return self.remove_meeting_registrant(meeting_id, registrant_id)

    def remove_from_multiple_meetings(
        self,
        meeting_ids: list[str],
        email: str
    ) -> dict:
        """
        Remove a user from multiple meetings by email.

        Used during offboarding to remove intern from all meetings.

        Args:
            meeting_ids: List of Zoom meeting IDs
            email: User's email address

        Returns:
            dict with success status and per-meeting results
        """
        results = {
            "success": True,
            "meetings": [],
            "errors": []
        }

        for meeting_id in meeting_ids:
            result = self.remove_registrant_by_email(
                meeting_id=meeting_id,
                email=email
            )

            if result.get("success"):
                results["meetings"].append({
                    "meeting_id": meeting_id,
                    "status": result.get("status", "removed")
                })
            else:
                results["errors"].append({
                    "meeting_id": meeting_id,
                    "error": result.get("error")
                })
                results["success"] = False

        return results
