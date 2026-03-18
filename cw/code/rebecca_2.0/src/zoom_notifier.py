"""
Zoom webhook notification sender.
"""
import logging
import sys
import time
from typing import Optional

import requests

from .utils import retry_with_backoff


class ZoomNotifier:
    """Send notifications to Zoom via incoming webhook."""

    # Zoom has message size limits
    MAX_MESSAGE_LENGTH = 4000

    def __init__(self, webhook_url: Optional[str] = None, logger: logging.Logger = None):
        """
        Initialize the Zoom notifier.

        Args:
            webhook_url: Zoom incoming webhook URL
            logger: Logger instance
        """
        self.webhook_url = webhook_url
        self.logger = logger or logging.getLogger("qa_agent")

    @retry_with_backoff(
        max_retries=3,
        base_delay=2.0,
        exceptions=(requests.exceptions.Timeout, requests.exceptions.ConnectionError)
    )
    def _post_to_webhook(self, message: str, timeout: int) -> requests.Response:
        """Post message to webhook with retry logic."""
        return requests.post(
            self.webhook_url,
            json={"content": message},
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )

    def send(self, message: str, timeout: int = 30) -> bool:
        """
        Send a message to Zoom.

        Args:
            message: The message content to send
            timeout: Request timeout in seconds

        Returns:
            True if successful, False otherwise
        """
        if not self.webhook_url:
            self.logger.info("No Zoom webhook configured. Printing report to console.")
            print("-" * 60)
            print(message)
            print("-" * 60)
            return False

        # Truncate if too long (with warning)
        if len(message) > self.MAX_MESSAGE_LENGTH:
            self.logger.warning(
                f"Message truncated from {len(message)} to {self.MAX_MESSAGE_LENGTH} chars"
            )
            message = message[:self.MAX_MESSAGE_LENGTH - 50] + "\n\n... (truncated)"

        try:
            response = self._post_to_webhook(message, timeout)
            response.raise_for_status()
            self.logger.info("Report posted to Zoom successfully")
            return True

        except requests.exceptions.Timeout:
            self.logger.error("Zoom webhook request timed out after retries")
            return False
        except requests.exceptions.ConnectionError:
            self.logger.error("Could not connect to Zoom webhook after retries")
            return False
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Zoom webhook returned HTTP {e.response.status_code}")
            return False
        except Exception as e:
            self.logger.error(f"Error sending to Zoom: {e}")
            return False

    def send_with_fallback(self, message: str, fallback_path: str = "report_fallback.md") -> bool:
        """
        Send message to Zoom, falling back to local file on failure.

        Args:
            message: The message content to send
            fallback_path: Path to save report if Zoom fails

        Returns:
            True if sent to Zoom, False if saved to fallback file
        """
        if self.send(message):
            return True

        # Fallback: save to local file
        try:
            with open(fallback_path, "w", encoding="utf-8") as f:
                f.write(message)
            self.logger.warning(f"Report saved to fallback file: {fallback_path}")
            return False
        except Exception as e:
            self.logger.critical(f"Failed to save fallback file: {e}")
            raise
