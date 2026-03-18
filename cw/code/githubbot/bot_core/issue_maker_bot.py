import os
import logging
import json
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ZoomIssueMakerBot:
    """Zoom bot specifically for the GitHub Issue Maker app"""

    def __init__(self):
        logger.info("Initializing Zoom Issue Maker Bot")
        self.client_id = os.environ.get('ZOOM_ISSUE_MAKER_CLIENT_ID')
        self.client_secret = os.environ.get('ZOOM_ISSUE_MAKER_CLIENT_SECRET')
        self.bot_jid = os.environ.get('ZOOM_ISSUE_MAKER_BOT_JID')
        self.account_id = os.environ.get('ZOOM_ACCOUNT_ID')  # Shared account ID
        self.devops_channel_id = os.environ.get('ZOOM_DEVOPS_CHANNEL_ID')

        logger.info("Checking Issue Maker Bot credentials:")
        logger.info(f"- Client ID: {'✓ Present' if self.client_id else '✗ Missing'}")
        logger.info(f"- Client Secret: {'✓ Present' if self.client_secret else '✗ Missing'}")
        logger.info(f"- Bot JID: {'✓ Present' if self.bot_jid else '✗ Missing'}")
        logger.info(f"- Account ID: {'✓ Present' if self.account_id else '✗ Missing'}")
        logger.info(f"- DevOps Channel ID: {'✓ Present' if self.devops_channel_id else '✗ Missing'}")

        if not all([self.client_id, self.client_secret, self.bot_jid, self.account_id]):
            logger.warning("Missing Issue Maker Bot credentials - bot will be disabled")
            self.enabled = False
        else:
            self.enabled = True

        self.access_token = None
        self.token_expiry = None
        logger.info(f"Zoom Issue Maker Bot initialized (enabled: {self.enabled})")

    def _get_access_token(self):
        """Get a new access token using client credentials"""
        if self.access_token and self.token_expiry and datetime.now() < self.token_expiry:
            return self.access_token

        logger.info("Getting new Issue Maker Bot access token")
        url = "https://zoom.us/oauth/token"
        auth = (self.client_id, self.client_secret)
        data = {
            'grant_type': 'client_credentials',
            'account_id': self.account_id
        }

        try:
            response = requests.post(url, auth=auth, data=data)
            response.raise_for_status()
            token_data = response.json()

            self.access_token = token_data['access_token']
            expires_in = int(token_data['expires_in']) - 60
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in)

            logger.info(f"Successfully obtained Issue Maker access token (expires in {expires_in}s)")
            return self.access_token

        except Exception as e:
            logger.error(f"Error getting Issue Maker access token: {str(e)}", exc_info=True)
            raise

    def send_message(self, message, to_jid=None):
        """Send a message to a Zoom channel"""
        if not self.enabled:
            logger.error("Issue Maker Bot is not enabled")
            return None

        # Default to devops channel if no specific channel provided
        target_jid = to_jid or self.devops_channel_id
        if not target_jid:
            logger.error("No target channel specified and no devops channel configured")
            return None

        try:
            token = self._get_access_token()

            url = "https://api.zoom.us/v2/im/chat/messages"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }

            if isinstance(message, str):
                content = {
                    'head': {
                        'text': 'GitHub Issue Creator'
                    },
                    'body': [{
                        'type': 'message',
                        'text': message
                    }]
                }
            else:
                content = message

            data = {
                'robot_jid': self.bot_jid,
                'to_jid': target_jid,
                'account_id': self.account_id,
                'content': content
            }

            logger.debug(f"Sending Issue Maker message to {target_jid}")
            response = requests.post(url, headers=headers, json=data)

            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response body: {response.text}")

            if response.status_code not in [200, 201]:
                logger.error(f"Zoom API error: {response.status_code} - {response.text}")

            response.raise_for_status()
            logger.info("Issue Maker message sent successfully")
            return response.json()

        except Exception as e:
            logger.error(f"Failed to send Issue Maker message: {str(e)}", exc_info=True)
            raise

    def delete_message(self, message_id, to_jid=None):
        """Delete a message from Zoom chat"""
        if not self.enabled:
            logger.error("Issue Maker Bot is not enabled")
            return False

        target_jid = to_jid or self.devops_channel_id
        if not target_jid:
            logger.error("No target channel specified")
            return False

        try:
            token = self._get_access_token()

            url = f"https://api.zoom.us/v2/im/chat/messages/{message_id}"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            params = {
                'robot_jid': self.bot_jid,
                'account_id': self.account_id,
                'to_jid': target_jid
            }

            logger.debug(f"Deleting message {message_id}")
            response = requests.delete(url, headers=headers, params=params)

            logger.debug(f"Delete response status: {response.status_code}")
            if response.status_code in [200, 204]:
                logger.info(f"Message {message_id} deleted successfully")
                return True
            else:
                logger.error(f"Failed to delete message: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to delete message: {str(e)}", exc_info=True)
            return False


# Initialize the bot when Django starts
logger.info("Attempting to initialize Issue Maker bot")
try:
    issue_maker_bot = ZoomIssueMakerBot()
    logger.info("Issue Maker bot initialized successfully")
except Exception as e:
    logger.error("Failed to initialize Issue Maker bot", exc_info=True)
    issue_maker_bot = None
