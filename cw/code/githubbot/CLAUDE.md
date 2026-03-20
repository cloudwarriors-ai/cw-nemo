# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Django-based integration bot that bridges GitHub and Zoom. It receives GitHub webhook events, generates AI commentary using OpenAI, and relays notifications to Zoom Chat. Users can also interact with the bot via Zoom slash commands to chat with AI or create GitHub issues.

## Common Commands

### Development
```bash
# Run development server (uses Django runserver on port 5000)
python manage.py runserver 0.0.0.0:5000

# Run with ngrok tunnel (for webhook testing)
./start.sh

# Run migrations
python manage.py makemigrations && python manage.py migrate
```

### Production
```bash
# Run with Daphne ASGI server
daphne -b 0.0.0.0 -p 5000 github_bot_project.asgi:application

# Docker deployment
docker-compose up -d
```

## Architecture

### Request Flow

1. **GitHub Webhooks** → `POST /api/webhook/` → `views.webhook()`:
   - Verifies HMAC-SHA256 signature
   - Parses event (push, pull_request, issues, issue_comment)
   - Generates AI commentary via `llm_bot.generate_response()`
   - Sends formatted message to Zoom via `zoom_bot.send_message()`
   - Stores event in database
   - Broadcasts to WebSocket group `github_events`

2. **Zoom Bot Commands** → `POST /command/` → `views.zoom_command()`:
   - Parses command from Zoom payload
   - Routes to `handle_zoom_command()` (help, events, chat, issue, whoami)
   - For `chat` command, uses OpenAI to generate response
   - For `issue` command, starts multi-step conversation flow
   - Sends response back to Zoom

3. **GitHub Issue Maker** → `POST /issue-command/` → `views.issue_command()`:
   - Dedicated Zoom app for creating GitHub issues
   - Handles slash commands, button clicks, and form edits
   - Uses `IssueConversation` model to track multi-step state
   - Creates issues via `github_bot.create_issue()`

4. **WebSocket** → `ws/github/events/` → `GitHubEventConsumer`:
   - Real-time event broadcasting to connected web clients
   - Handles `github_event` and `container_heartbeat` message types

### Key Components

| File | Purpose |
|------|---------|
| `bot_core/views.py` | HTTP endpoints, webhook handling, Zoom command routing |
| `bot_core/consumers.py` | WebSocket consumer for real-time events |
| `bot_core/llm_bot.py` | OpenAI client wrapper (`LLMBot` class) |
| `bot_core/zoom_bot.py` | Zoom OAuth2 and Chat API client (`ZoomChatBot` class) |
| `bot_core/github_bot.py` | GitHub API client for issue creation (`GitHubBot` class) |
| `bot_core/issue_maker_bot.py` | Dedicated Zoom bot for issue creation (`ZoomIssueMakerBot` class) |
| `bot_core/routing.py` | WebSocket URL routing |
| `github_bot_project/asgi.py` | ASGI config with Channels ProtocolTypeRouter |

### Models

- **Repository**: Tracked GitHub repos (`full_name`, `github_id`)
- **WebhookEvent**: Stored webhook events with extracted metadata (actor, action, title, commits, html_url, etc.)
- **ZoomCommand**: Logged Zoom slash commands
- **Application**: Maps application names to GitHub repos for issue creation
- **IssueConversation**: Tracks multi-step conversation state for issue creation (state machine: `awaiting_app` → `awaiting_description` → `completed`)

### Integration Singletons

All bots are instantiated at module import time as singletons:
- `bot_core/llm_bot.py` - `llm_bot = LLMBot()`
- `bot_core/zoom_bot.py` - `zoom_bot = ZoomChatBot()`
- `bot_core/github_bot.py` - `github_bot = GitHubBot()`
- `bot_core/issue_maker_bot.py` - `issue_maker_bot = ZoomIssueMakerBot()`

## Environment Variables

Required in `.env`:
```
DJANGO_SECRET_KEY=
GITHUB_WEBHOOK_SECRET=
OPENAI_API_KEY=
ZOOM_CLIENT_ID=
ZOOM_CLIENT_SECRET=
ZOOM_BOT_JID=
ZOOM_CHANNEL_ID=
ZOOM_ACCOUNT_ID=
```

For GitHub issue creation:
```
GITHUB_TOKEN=  # Personal access token with repo scope
```

For Issue Maker Zoom app:
```
ZOOM_ISSUE_MAKER_CLIENT_ID=
ZOOM_ISSUE_MAKER_CLIENT_SECRET=
ZOOM_ISSUE_MAKER_BOT_JID=
ZOOM_DEVOPS_CHANNEL_ID=
```

Optional:
```
OPENAI_MODEL=gpt-4
OPENAI_MAX_TOKENS=1000
OPENAI_TEMPERATURE=0.7
ZOOM_PROD_CHANNEL_ID=  # For critical alerts
```

## URL Routes

| Path | Handler | Purpose |
|------|---------|---------|
| `POST /api/webhook/` | `views.webhook` | GitHub webhook receiver |
| `POST /webhook/` | `views.webhook` | Alternative webhook endpoint |
| `POST /command/` | `views.zoom_command` | Zoom slash commands |
| `POST /issue-command/` | `views.issue_command` | Issue Maker Zoom commands |
| `GET /events/` | `views.list_events` | Web dashboard |
| `GET /webhooks/` | `views.webhook_list` | Paginated event history |
| `WS /ws/github/events/` | `GitHubEventConsumer` | Real-time events |

## Async Patterns

Views use Django's async support with `sync_to_async` for ORM operations:
```python
repository, _ = await sync_to_async(Repository.objects.get_or_create)(...)
```

Channel layer broadcasts use `await channel_layer.group_send(...)` to push events to WebSocket consumers.
