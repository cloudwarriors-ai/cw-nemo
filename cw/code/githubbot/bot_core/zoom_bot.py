import os
import logging
import json
import requests
from datetime import datetime, timedelta

# Configure logging
logger = logging.getLogger(__name__)

class ZoomChatBot:
    def __init__(self):
        logger.info("Initializing Zoom Chat Bot")
        # Load credentials
        self.client_id = os.environ.get('ZOOM_CLIENT_ID')
        self.client_secret = os.environ.get('ZOOM_CLIENT_SECRET')
        self.bot_jid = os.environ.get('ZOOM_BOT_JID')
        self.channel_id = os.environ.get('ZOOM_CHANNEL_ID')
        self.prod_channel_id = os.environ.get('ZOOM_PROD_CHANNEL_ID')
        self.devops_channel_id = os.environ.get('ZOOM_DEVOPS_CHANNEL_ID')
        self.account_id = os.environ.get('ZOOM_ACCOUNT_ID')

        # Log credential status (without exposing secrets)
        logger.info("Checking Zoom credentials:")
        logger.info(f"- Client ID: {'✓ Present' if self.client_id else '✗ Missing'}")
        logger.info(f"- Client Secret: {'✓ Present' if self.client_secret else '✗ Missing'}")
        logger.info(f"- Bot JID: {'✓ Present' if self.bot_jid else '✗ Missing'}")
        logger.info(f"- Channel ID: {'✓ Present' if self.channel_id else '✗ Missing'}")
        logger.info(f"- DevOps Channel ID: {'✓ Present' if self.devops_channel_id else '✗ Missing'}")
        logger.info(f"- Account ID: {'✓ Present' if self.account_id else '✗ Missing'}")
        
        if not all([self.client_id, self.client_secret, self.bot_jid, self.channel_id, self.account_id]):
            logger.error("Missing required Zoom credentials in environment variables")
            raise ValueError("Missing required Zoom credentials in environment variables")
            
        self.access_token = None
        self.token_expiry = None
        logger.info("Zoom Chat Bot initialized successfully")
        
    def _get_access_token(self):
        """Get a new access token using client credentials"""
        if self.access_token and self.token_expiry and datetime.now() < self.token_expiry:
            logger.debug("Using existing access token")
            return self.access_token
            
        logger.info("Getting new Zoom access token")
        url = "https://zoom.us/oauth/token"
        auth = (self.client_id, self.client_secret)
        data = {
            'grant_type': 'client_credentials',
            'account_id': self.account_id
        }
        
        try:
            logger.debug(f"Making token request to {url}")
            logger.debug(f"Using client_id: {self.client_id[:4]}... and account_id: {self.account_id}")
            
            response = requests.post(url, auth=auth, data=data)
            
            # Log response details for debugging
            logger.debug(f"Token response status: {response.status_code}")
            logger.debug(f"Token response headers: {json.dumps(dict(response.headers), indent=2)}")
            logger.debug(f"Token response body: {response.text}")
            
            response.raise_for_status()
            token_data = response.json()
            
            self.access_token = token_data['access_token']
            # Set expiry to slightly less than the actual expiry time
            expires_in = int(token_data['expires_in']) - 60
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in)
            
            logger.info(f"Successfully obtained new access token (expires in {expires_in} seconds)")
            return self.access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting Zoom access token: {str(e)}", exc_info=True)
            if hasattr(e, 'response') and e.response:
                logger.error(f"Error response body: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting Zoom access token: {str(e)}", exc_info=True)
            raise
    
    def send_message(self, message, to_jid=None):
        """Send a message to a Zoom channel

        Args:
            message: The message content (string or dict)
            to_jid: Optional channel JID to send to. If not provided, uses default ZOOM_CHANNEL_ID.
        """
        try:
            token = self._get_access_token()

            url = "https://api.zoom.us/v2/im/chat/messages"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }

            # Format message for Zoom Chat API
            if isinstance(message, str):
                content = {
                    'head': {
                        'text': 'GitHub Bot'
                    },
                    'body': [{
                        'type': 'message',
                        'text': message
                    }]
                }
            else:
                content = message

            # Use provided channel or fall back to default
            target_channel = to_jid if to_jid else self.channel_id

            data = {
                'robot_jid': self.bot_jid,
                'to_jid': target_channel,
                'account_id': self.account_id,
                'content': content
            }
            
            logger.debug(f"Sending message to {url}")
            logger.debug(f"Request headers: {json.dumps({k: v for k, v in headers.items() if k.lower() != 'authorization'}, indent=2)}")
            logger.debug(f"Message data: {json.dumps(data, indent=2)}")
            
            response = requests.post(url, headers=headers, json=data)
            
            # Log response details regardless of status
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {json.dumps(dict(response.headers), indent=2)}")
            logger.debug(f"Response body: {response.text}")
            
            # Check if we got an error response (200 and 201 are both success)
            if response.status_code not in [200, 201]:
                error_msg = f"Zoom API error: {response.status_code}"
                try:
                    error_data = response.json()
                    if 'message' in error_data:
                        error_msg += f" - {error_data['message']}"
                except:
                    error_msg += f" - {response.text}"
                logger.error(error_msg)
                
            response.raise_for_status()
            
            logger.info("Message sent successfully")
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send message: {str(e)}", exc_info=True)
            if hasattr(e, 'response') and e.response:
                try:
                    error_detail = e.response.json()
                    logger.error(f"Error response detail: {json.dumps(error_detail, indent=2)}")
                except:
                    logger.error(f"Error response body: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error sending message: {str(e)}", exc_info=True)
            raise

    def send_message_to_devops(self, message):
        """Send a message to the DevOps Zoom channel"""
        if not self.devops_channel_id:
            logger.warning("DevOps channel ID not configured, falling back to default channel")
            return self.send_message(message)

        try:
            token = self._get_access_token()

            url = "https://api.zoom.us/v2/im/chat/messages"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }

            # Format message for Zoom Chat API
            if isinstance(message, str):
                content = {
                    'head': {
                        'text': 'GitHub Issue Bot'
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
                'to_jid': self.devops_channel_id,
                'account_id': self.account_id,
                'content': content
            }

            logger.debug(f"Sending message to DevOps channel")
            logger.debug(f"Message data: {json.dumps(data, indent=2)}")

            response = requests.post(url, headers=headers, json=data)

            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response body: {response.text}")

            if response.status_code not in [200, 201]:
                error_msg = f"Zoom API error: {response.status_code}"
                try:
                    error_data = response.json()
                    if 'message' in error_data:
                        error_msg += f" - {error_data['message']}"
                except:
                    error_msg += f" - {response.text}"
                logger.error(error_msg)

            response.raise_for_status()

            logger.info("Message sent to DevOps channel successfully")
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send message to DevOps: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error sending message to DevOps: {str(e)}", exc_info=True)
            raise

    def get_member_info(self, member_id):
        """Get detailed information about a Zoom chat member"""
        try:
            token = self._get_access_token()
            
            url = f"https://api.zoom.us/v2/chat/users/{member_id}"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            logger.debug(f"Getting member info from {url}")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            member_data = response.json()
            logger.info(f"Retrieved member info: {json.dumps(member_data, indent=2)}")
            
            return member_data
            
        except Exception as e:
            logger.error(f"Failed to get member info: {str(e)}", exc_info=True)
            raise

    def announce_online(self):
        """Send an announcement that the bot is online"""
        logger.info("Sending bot online announcement to Zoom")
        message = "🟢 GitHub Bot is now online and ready to relay updates!"
        try:
            self.send_message(message)
            logger.info("Successfully sent online announcement to Zoom")
        except Exception as e:
            logger.error("Failed to send online announcement", exc_info=True)

# Initialize the bot when Django starts
logger.info("Attempting to initialize Zoom bot")
try:
    zoom_bot = ZoomChatBot()
    logger.info("Zoom bot initialized successfully")
except Exception as e:
    logger.error("Failed to initialize Zoom bot", exc_info=True)
    zoom_bot = None
