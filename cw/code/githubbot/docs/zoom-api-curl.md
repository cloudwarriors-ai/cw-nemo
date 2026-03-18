# Zoom Chat Bot API - Curl Examples

## Step 1: Get Access Token

First, obtain an OAuth access token using client credentials:

```bash
curl -X POST "https://zoom.us/oauth/token" \
  -u "${ZOOM_CLIENT_ID}:${ZOOM_CLIENT_SECRET}" \
  -d "grant_type=client_credentials" \
  -d "account_id=${ZOOM_ACCOUNT_ID}"
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzUxMiIsInYiOiIyLjAi...",
  "token_type": "bearer",
  "expires_in": 3600,
  "scope": "..."
}
```

## Step 2: Send Message to Channel

Using the access token, send a message to a Zoom channel:

```bash
curl -X POST "https://api.zoom.us/v2/im/chat/messages" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "robot_jid": "'${ZOOM_BOT_JID}'",
    "to_jid": "'${ZOOM_CHANNEL_ID}'",
    "account_id": "'${ZOOM_ACCOUNT_ID}'",
    "content": {
      "head": {
        "text": "Message Header"
      },
      "body": [
        {
          "type": "message",
          "text": "Your message content here"
        }
      ]
    }
  }'
```

**Response (201 Created):**
```json
{
  "robot_jid": "v1pdir6z5eqr6zcf6nc6upng@xmpp.zoom.us",
  "to_jid": "4717cba177784fdc8b21b874085cdc42@conference.xmpp.zoom.us",
  "sent_time": "2026-01-28 22:06:07",
  "message_id": "20260128220607336_mlfAazV_aw1"
}
```

## One-Liner (Combined)

Get token and send message in one command:

```bash
ACCESS_TOKEN=$(curl -s -X POST "https://zoom.us/oauth/token" \
  -u "${ZOOM_CLIENT_ID}:${ZOOM_CLIENT_SECRET}" \
  -d "grant_type=client_credentials" \
  -d "account_id=${ZOOM_ACCOUNT_ID}" | jq -r '.access_token') && \
curl -X POST "https://api.zoom.us/v2/im/chat/messages" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "robot_jid": "'${ZOOM_BOT_JID}'",
    "to_jid": "'${ZOOM_CHANNEL_ID}'",
    "account_id": "'${ZOOM_ACCOUNT_ID}'",
    "content": {
      "head": {
        "text": "Test Message"
      },
      "body": [
        {
          "type": "message",
          "text": "Hello from curl!"
        }
      ]
    }
  }'
```

## Environment Variables Required

| Variable | Description | Example |
|----------|-------------|---------|
| `ZOOM_CLIENT_ID` | OAuth app client ID | `abc123...` |
| `ZOOM_CLIENT_SECRET` | OAuth app client secret | `xyz789...` |
| `ZOOM_ACCOUNT_ID` | Zoom account ID | `98cKrPiRQUanKn9bULRWnA` |
| `ZOOM_BOT_JID` | Bot's JID (Jabber ID) | `v1pdir6z5eqr6zcf6nc6upng@xmpp.zoom.us` |
| `ZOOM_CHANNEL_ID` | Target channel JID | `4717cba177784fdc8b21b874085cdc42@conference.xmpp.zoom.us` |

## Message Content Types

### Simple Text Message
```json
{
  "head": {
    "text": "Header Text"
  },
  "body": [
    {
      "type": "message",
      "text": "Your message here with *bold* and _italic_"
    }
  ]
}
```

### Message with Action Buttons
```json
{
  "head": {
    "text": "Choose an Option"
  },
  "body": [
    {
      "type": "message",
      "text": "Select one of the following:"
    },
    {
      "type": "actions",
      "items": [
        {
          "text": "Option 1",
          "value": "option_1",
          "style": "Primary"
        },
        {
          "text": "Option 2",
          "value": "option_2",
          "style": "Default"
        },
        {
          "text": "Cancel",
          "value": "cancel",
          "style": "Danger"
        }
      ]
    }
  ]
}
```

## Notes

- Access tokens expire after ~1 hour (3600 seconds)
- Successful message send returns HTTP 201 (not 200)
- Channel JIDs ending in `@conference.xmpp.zoom.us` are group channels
- User JIDs ending in `@xmpp.zoom.us` are direct messages
