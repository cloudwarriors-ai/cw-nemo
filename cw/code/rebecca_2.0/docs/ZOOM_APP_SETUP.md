# Zoom Team Chat App Setup Guide

This guide walks through setting up the QA Bot as a Zoom Team Chat application.

## Prerequisites

- Zoom account with Admin privileges (or owner permission)
- Public HTTPS endpoint for webhooks (or ngrok for development)
- The QA Continuity Bot deployed and accessible

## Step 1: Create a Zoom App

1. Go to [Zoom Marketplace](https://marketplace.zoom.us/)
2. Click **Develop** > **Build App**
3. Select **Team Chat Apps** as the app type
4. Click **Create**

### App Information

Fill in the basic information:

| Field | Value |
|-------|-------|
| App Name | QA Bot (or your preferred name) |
| Short Description | AI-powered QA assistant for issue tracking and team coordination |
| Company Name | Your organization |
| Developer Name | Your name |
| Developer Email | Your email |

## Step 2: Configure App Credentials

After creation, you'll see your app credentials:

### Bot Credentials (Team Chat Apps)

- **Bot JID**: Copy this for your configuration
- **Verification Token**: Copy to `ZOOM_BOT_TOKEN` in your `.env`

### Webhook Secret (for URL Validation)

1. Go to **Feature** > **Team Chat**
2. Enable **Team Chat Subscription**
3. Note the **Secret Token** - copy to `ZOOM_WEBHOOK_SECRET` in your `.env`

## Step 3: Configure Webhook Endpoint

### Set Endpoint URL

1. In app settings, go to **Feature** > **Team Chat**
2. Set **Bot endpoint URL**: `https://your-domain.com/zoom/webhook`
3. Click **Validate** - Zoom will send a challenge request

### Webhook Events

Enable the following events under Team Chat subscription:

- `bot_notification` - Required for receiving messages to your bot
- `bot_installed` - Optional, for tracking installations

## Step 4: Configure Scopes

Go to **Scopes** and add:

### Required Scopes

| Scope | Purpose |
|-------|---------|
| `team_chat:write` | Send messages to Team Chat |
| `team_chat:read` | Read messages from Team Chat |
| `user:read` | Get user information |

### Optional Scopes (if using meeting features)

| Scope | Purpose |
|-------|---------|
| `meeting:read` | Read meeting information |
| `meeting:write` | Create/update meetings |

## Step 5: Installation & Authorization

### For Development

1. Go to **Local Test** in your app settings
2. Click **Add** to install the app to your account
3. The bot will appear in your Team Chat sidebar

### For Production

1. Submit your app for review (see below)
2. Once approved, users can install from Marketplace
3. Or use **Pre-approve** for organization-wide deployment

## Step 6: Environment Configuration

Update your `.env` file with Zoom credentials:

```bash
# Zoom Configuration
ZOOM_BOT_TOKEN=your-verification-token-here
ZOOM_WEBHOOK_SECRET=your-webhook-secret-here

# Optional: Bot display settings
ZOOM_BOT_JID=your-bot-jid-here
```

## Step 7: Testing the Integration

### Test with ngrok (Development)

1. Start ngrok: `ngrok http 5000`
2. Copy the HTTPS URL (e.g., `https://abc123.ngrok.io`)
3. Update your Zoom app endpoint: `https://abc123.ngrok.io/zoom/webhook`
4. Click **Validate** in Zoom
5. Start your bot: `python -m flask --app src.bot.app:app run`
6. Send a message to the bot in Team Chat

### Verify Webhook Works

Send test messages:
- `@qabot help` - Should return help text
- `@qabot high priority` - Should return high priority issues
- `@qabot status` - Should return project status

### Check Logs

Monitor your application logs for:
```
Received Zoom webhook: ...
Processing query: help
Sending response: ...
```

## URL Validation Flow

When you set your webhook URL, Zoom sends a validation challenge:

1. Zoom sends POST to your endpoint with:
   ```json
   {
     "event": "endpoint.url_validation",
     "payload": {
       "plainToken": "random-token-string"
     }
   }
   ```

2. Your app must respond with:
   ```json
   {
     "plainToken": "random-token-string",
     "encryptedToken": "hmac-sha256-of-token"
   }
   ```

The QA Bot handles this automatically in `/zoom/webhook`.

## HMAC Signature Verification

For production security, Zoom signs webhook requests:

1. Each request includes headers:
   - `x-zm-signature`: HMAC-SHA256 signature
   - `x-zm-request-timestamp`: Unix timestamp

2. Signature is computed as:
   ```
   message = "v0:" + timestamp + ":" + request_body
   signature = "v0=" + HMAC-SHA256(secret, message)
   ```

3. The bot verifies this signature before processing

Enable this by setting `ZOOM_WEBHOOK_SECRET` in your environment.

## Marketplace Submission

### Pre-Submission Checklist

- [ ] App tested with real users
- [ ] All scopes are necessary and documented
- [ ] Privacy policy URL provided
- [ ] Terms of service URL provided
- [ ] Support contact information provided
- [ ] App icon (96x96 PNG) uploaded
- [ ] Screenshots provided
- [ ] Long description completed

### Submission Process

1. Go to **Submit** in your app dashboard
2. Fill in all required fields
3. Provide test credentials if needed
4. Submit for review

### Review Timeline

- Initial review: 1-2 weeks
- May require revisions
- Final approval: 1-2 additional weeks

## Troubleshooting

### Bot Not Receiving Messages

1. Check endpoint URL is correct and validated
2. Verify `ZOOM_BOT_TOKEN` matches the token in Zoom
3. Check your firewall allows incoming HTTPS requests
4. Review application logs for errors

### 401 Unauthorized Errors

1. Verify `ZOOM_BOT_TOKEN` is correct
2. Check `ZOOM_WEBHOOK_SECRET` if using HMAC verification
3. Ensure the token hasn't been regenerated in Zoom

### URL Validation Failing

1. Ensure your endpoint is publicly accessible via HTTPS
2. Check `ZOOM_WEBHOOK_SECRET` is set correctly
3. Verify your app responds within 3 seconds
4. Check logs for the validation request

### Messages Not Sending

1. Verify `team_chat:write` scope is granted
2. Check bot has access to the channel
3. Verify response format is correct JSON

## Webhook Retries and Idempotency

Zoom retries failed webhook deliveries:

- **Retry attempts**: Up to 3 retries on failure
- **Retry interval**: Exponential backoff (seconds to minutes)
- **Timeout**: Zoom expects response within 3 seconds

### Handling Duplicate Webhooks

If your app is slow or temporarily down, you may receive duplicate events. Handle this with idempotency:

```python
# Track processed events
processed_events = set()

def handle_webhook(event_id, payload):
    # Skip if already processed
    if event_id in processed_events:
        return {"status": "already_processed"}

    # Process the event
    result = process_payload(payload)

    # Mark as processed
    processed_events.add(event_id)

    return result
```

**Best practices:**
1. Use unique event IDs (from payload) for deduplication
2. Store processed event IDs in Redis or database for persistence
3. Set TTL on stored IDs (e.g., 24 hours) to prevent unbounded growth
4. Return 200 OK quickly, process asynchronously if needed

## Security Best Practices

1. **Always use HTTPS** for your webhook endpoint
2. **Enable HMAC verification** with `ZOOM_WEBHOOK_SECRET`
3. **Validate all input** before processing
4. **Rate limit requests** to prevent abuse
5. **Log webhook events** for debugging and auditing
6. **Rotate tokens periodically** and update your configuration
7. **Handle duplicates** with idempotency (see above)

## Reference Links

- [Zoom Team Chat Apps Documentation](https://developers.zoom.us/docs/team-chat-apps/)
- [Webhook Reference](https://developers.zoom.us/docs/api/rest/webhook-reference/)
- [Marketplace Submission Guide](https://developers.zoom.us/docs/publish/)
- [OAuth Scopes Reference](https://developers.zoom.us/docs/integrations/oauth-scopes/)
