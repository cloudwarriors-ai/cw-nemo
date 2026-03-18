# QA Continuity App

AI-powered QA Lead system for Cloud Warriors. Provides conversational interface via Zoom Team Chat, joins meetings with an animated avatar, and handles QA tasks automatically.

## Features

### Phase 1: Interactive Chat Bot
- **Zoom Team Chat Integration**: Respond to queries in real-time
- **GitHub Issue Queries**: "high priority", "unassigned", "stale issues"
- **Intern Management**: Track tasks, status, and assignments
- **Human Escalation**: Automatic handoff for sensitive topics
- **Rate Limiting**: Protect against abuse

### Phase 2: Workflow Automation (n8n)
- **Onboarding Workflows**: Automated new intern setup
- **Offboarding Workflows**: End-of-internship procedures
- **Weekly Reminders**: Automated feedback prep

### Phase 3: Meeting Presence (Recall.ai)
- **Join Zoom Meetings**: Bot joins with custom avatar
- **Real-time Transcription**: Capture meeting audio
- **Meeting Notes**: Generate summaries automatically
- **Keyword Alerts**: Notify on important topics

### Phase 4: Voice & Avatar
- **Voice Pipeline**: Whisper ASR + Cartesia/OpenAI TTS
- **Animated Avatar**: Simli lip-synced avatar in meetings
- **Real-time Responses**: <3 second end-to-end latency
- **Semantic Caching**: 86% latency reduction for common queries

### Phase 5: Real-Time Platform (LiveKit)
- **LiveKit Integration**: WebRTC-based real-time communication
- **Deepgram STT**: Low-latency streaming speech-to-text
- **Simli Avatar**: Photorealistic animated avatar via LiveKit

### Enterprise Features
- **Structured Logging**: JSON logs with request correlation
- **Audit Trail**: Compliance-ready audit logging
- **Circuit Breakers**: Resilient external API calls
- **Graceful Shutdown**: Clean shutdown with request draining
- **Input Validation**: Pydantic schemas for all API inputs

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone <repo-url>
cd qa_continuity_app

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Start with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Option 2: Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Run the bot
python -m flask --app src.bot.app:create_app run --debug

# Run tests
pytest tests/ -v
```

## Configuration

Copy `.env.example` to `.env` and configure:

### Required (Phase 1)
```bash
GITHUB_TOKEN=ghp_xxx              # GitHub API access
ZOOM_BOT_VERIFICATION_TOKEN=xxx   # Zoom chatbot token
ZOOM_BOT_SECRET_TOKEN=xxx         # Zoom HMAC secret (production)
API_KEY=xxx                       # API endpoint authentication (required in production)
```

### Optional (Phase 2-5)
```bash
# n8n Workflows
N8N_WEBHOOK_URL=https://your-n8n.com/webhook
N8N_CALLBACK_SECRET=xxx

# Meeting Bot (Recall.ai)
RECALL_API_KEY=xxx
RECALL_BOT_NAME="QA Bot"
RECALL_TRANSCRIPTION_SECRET=xxx  # Webhook HMAC verification

# Voice Pipeline
VOICE_ENABLED=true
OPENAI_API_KEY=sk-xxx     # For Whisper ASR
CARTESIA_API_KEY=xxx      # For low-latency TTS
DEEPGRAM_API_KEY=xxx      # For streaming STT (Phase 5)

# Avatar
AVATAR_ENABLED=true
SIMLI_API_KEY=xxx
SIMLI_FACE_ID=xxx         # Custom avatar face

# LiveKit (Phase 5)
LIVEKIT_URL=wss://xxx.livekit.cloud
LIVEKIT_API_KEY=xxx
LIVEKIT_API_SECRET=xxx

# LLM (OpenRouter)
OPENROUTER_API_KEY=xxx
MODEL=anthropic/claude-haiku-4.5

# SMS Notifications (Twilio)
TWILIO_ACCOUNT_SID=xxx
TWILIO_API_KEY_SID=xxx
TWILIO_API_KEY_SECRET=xxx
TWILIO_FROM_NUMBER=+1xxx
TWILIO_TO_NUMBER=+1xxx
```

See `.env.example` for full configuration options.

## API Endpoints

### Health & Status
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check |
| `/health?detailed=true` | GET | Full dependency checks |
| `/api/stats` | GET | Query statistics |

### Chat Bot (Phase 1)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/zoom/webhook` | POST | Zoom Team Chat webhook |
| `/api/query` | POST | Direct API query |
| `/api/cache/refresh` | POST | Force cache refresh |

### Meeting Bot (Phase 3)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/meeting/join` | POST | Join a meeting |
| `/api/meeting/<id>` | GET | Get meeting status |
| `/api/meeting/<id>/leave` | POST | Leave meeting |
| `/api/meeting/list` | GET | List active meetings |
| `/api/meeting/<id>/transcript` | GET | Get transcript |

### Voice (Phase 4)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/voice/status` | GET | Voice pipeline status |
| `/api/voice/tts` | POST | Text-to-speech |
| `/api/voice/query` | POST | Voice query processing |

### Avatar (Phase 4)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/avatar/status` | GET | Avatar session status |
| `/api/avatar/start/<meeting_id>` | POST | Start avatar |
| `/api/avatar/stop` | POST | Stop avatar |
| `/avatar/page` | GET | Avatar webpage (for Recall.ai) |

## Chat Commands

Send these to the bot in Zoom Team Chat:

| Command | Description |
|---------|-------------|
| `help` | Show available commands |
| `high priority` | List high-priority issues |
| `unassigned` | List unassigned issues |
| `stale` | Issues with no update in 14+ days |
| `intern status` | Current intern assignments |
| `weekly summary` | Aggregated stats |
| `escalate [topic]` | Request human help |

## Deployment

### Docker Deployment

```bash
# Build and start
docker-compose up -d --build

# View logs
docker-compose logs -f qa-bot

# Health check
curl http://localhost:5000/health

# Stop
docker-compose down
```

### Production Deployment

For production, use a service like Railway, Render, or a cloud VM:

1. **SSL Required**: Zoom webhooks require HTTPS
2. **Environment Variables**: Set all required variables
3. **Health Monitoring**: Use `/health?detailed=true` endpoint
4. **Logging**: Logs are written to `/app/logs/` in container

### Development with ngrok

For local development with Zoom webhooks:

```bash
# Start with ngrok profile
docker-compose --profile ngrok up

# Get public URL from ngrok dashboard
open http://localhost:4040

# Use the ngrok URL in Zoom app configuration
```

## Project Structure

```
qa_continuity_app/
├── src/
│   ├── bot/                      # Core application layer
│   │   ├── app.py               # Flask application factory (thin orchestrator)
│   │   ├── bootstrap.py         # Phased component initialization
│   │   ├── handlers.py          # Query and request handlers
│   │   ├── config.py            # Centralized configuration
│   │   ├── routes/              # Blueprint route handlers
│   │   │   ├── health.py        # Health check endpoints
│   │   │   ├── zoom.py          # Zoom webhook handlers
│   │   │   ├── meetings.py      # Meeting API endpoints
│   │   │   ├── interns.py       # Intern management endpoints
│   │   │   ├── workflows.py     # n8n workflow triggers
│   │   │   ├── voice.py         # Voice API endpoints
│   │   │   └── avatar.py        # Avatar API endpoints
│   │   ├── services/            # Business logic layer
│   │   │   ├── query_service.py # Query processing service
│   │   │   ├── rate_limit_service.py # Rate limiting service
│   │   │   └── auth_service.py  # Authentication service
│   │   ├── utils/               # Utility functions
│   │   │   ├── input_validation.py  # Input sanitization
│   │   │   ├── verification.py      # Webhook verification
│   │   │   ├── rate_limiting.py     # Rate limit helpers
│   │   │   └── formatters.py        # Response formatters
│   │   ├── middleware/          # Request middleware
│   │   │   └── security.py      # Security headers, HSTS
│   │   ├── result.py            # Result pattern (Ok/Err)
│   │   ├── validation.py        # Pydantic input validation
│   │   ├── structured_logging.py # JSON structured logging
│   │   ├── graceful_shutdown.py # Signal handlers
│   │   ├── audit.py             # Compliance audit logging
│   │   ├── circuit_breaker.py   # Circuit breaker pattern
│   │   ├── llm_brain.py         # OpenRouter LLM integration
│   │   ├── query_parser.py      # Keyword matching fallback
│   │   ├── cache.py             # Thread-safe issue caching
│   │   ├── database.py          # SQLite operations
│   │   ├── escalation.py        # Human handoff
│   │   └── n8n_client.py        # n8n workflow client
│   ├── meeting/                  # Phase 3: Meeting bot
│   │   ├── recall_client.py     # Recall.ai API client
│   │   ├── meeting_handler.py   # Meeting lifecycle management
│   │   ├── transcription.py     # Transcription processing
│   │   └── wake_word_detector.py # Voice command detection
│   ├── voice/                    # Phase 4: Voice pipeline
│   │   ├── speech_processor.py  # Whisper ASR + VAD
│   │   ├── tts_client.py        # TTS (Cartesia/OpenAI)
│   │   └── voice_pipeline.py    # Real-time voice processing
│   ├── avatar/                   # Phase 4: Avatar
│   │   ├── simli_client.py      # Simli API client
│   │   ├── avatar_session.py    # Avatar session management
│   │   └── websocket_manager.py # WebSocket connection management
│   ├── platform/                 # Phase 5: Real-time platform
│   │   ├── livekit_agent.py     # LiveKit WebRTC agent
│   │   └── zoom_sdk.py          # Zoom Meeting SDK
│   ├── github_client.py          # GitHub API wrapper
│   └── utils/                    # Shared utilities
│       └── logging.py           # Logging setup
├── tests/                        # 1000+ tests
│   ├── test_app.py              # Application tests
│   ├── test_sql_injection.py    # SQL injection prevention tests
│   ├── test_memory_leaks.py     # Memory bounds tests
│   ├── test_result.py           # Result pattern tests
│   ├── test_validation.py       # Pydantic validation tests
│   ├── test_structured_logging.py # Logging tests
│   ├── test_graceful_shutdown.py # Shutdown handler tests
│   ├── test_audit.py            # Audit logging tests
│   └── ...                      # Additional test modules
├── docs/                         # Documentation
├── data/                         # SQLite database
├── logs/                         # Log files
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements.in               # Unpinned deps for pip-compile
└── .env.example
```

## Architecture

### Design Patterns

| Pattern | Implementation | Purpose |
|---------|---------------|---------|
| **Application Factory** | `create_app()` in `app.py` | Clean Flask app initialization |
| **Phased Bootstrap** | `bootstrap.py` | Dependency-ordered component init |
| **Service Layer** | `services/` directory | Business logic separation |
| **Result Pattern** | `result.py` (Ok/Err) | Explicit error handling |
| **Circuit Breaker** | `circuit_breaker.py` | External API resilience |
| **Repository Pattern** | `database.py` | Data access abstraction |

### Layered Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Routes (Blueprints)                  │
│         health.py │ zoom.py │ meetings.py │ ...        │
├─────────────────────────────────────────────────────────┤
│                    Services Layer                       │
│     QueryService │ RateLimitService │ AuthService      │
├─────────────────────────────────────────────────────────┤
│                    Core Components                      │
│   LLMBrain │ IssueCache │ RecallClient │ VoicePipeline │
├─────────────────────────────────────────────────────────┤
│                    Infrastructure                       │
│  Database │ CircuitBreaker │ AuditLogger │ Cache       │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

```
Zoom Webhook → /zoom/webhook → AuthService (HMAC verify) → QueryService
    → LLM Brain (OpenRouter) or QueryParser (keywords) → IssueCache
    → ResponseBuilder → ZoomChatbot.send_message()
```

### Memory Safety

All in-memory caches are bounded with explicit size limits:

| Cache | Max Size | Eviction |
|-------|----------|----------|
| Message dedup | 10,000 entries | FIFO |
| Conversation history | 500 meetings | LRU |
| Semantic cache | 200 entries | LRU |
| Audio cache | 10 MB total | LRU |
| WebSocket connections | 100 connections | LRU + stale cleanup |

## Testing

```bash
# Run all tests (1000+)
pytest tests/ -v

# Run specific test file
pytest tests/test_avatar.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run architecture-specific tests
pytest tests/test_sql_injection.py tests/test_memory_leaks.py -v
```

## Zoom App Setup

### 1. Create Zoom App
1. Go to [Zoom Marketplace](https://marketplace.zoom.us/)
2. Develop > Build App > Team Chat Apps
3. Configure OAuth scopes: `team_chat:read`, `team_chat:write`

### 2. Configure Webhooks
1. Features > Team Chat > Add Slash Command
2. Set webhook URL: `https://your-domain.com/zoom/webhook`
3. Copy Verification Token to `.env`
4. Copy Secret Token for HMAC verification

### 3. Submit for Review (Production)
1. Complete app information
2. Submit for Zoom review (2-4 weeks)
3. Once approved, publish to your account

## Troubleshooting

### Bot not responding
1. Check `/health` endpoint returns OK
2. Verify `ZOOM_BOT_VERIFICATION_TOKEN` is correct
3. Check logs: `docker-compose logs qa-bot`

### Meeting bot not joining
1. Verify `RECALL_API_KEY` is set
2. Check meeting URL format is valid
3. Verify meeting allows bots to join

### Voice not working
1. Set `VOICE_ENABLED=true`
2. Verify `OPENAI_API_KEY` or `CARTESIA_API_KEY` is set
3. Check `/api/voice/status` endpoint

### Avatar not showing
1. Set `AVATAR_ENABLED=true`
2. Verify `SIMLI_API_KEY` is set
3. Ensure meeting joined with `web_gpu` variant

## Security

### Authentication & Authorization
- **HMAC Verification**: Zoom/Recall.ai webhooks verified using HMAC-SHA256
- **API Authentication**: All `/api/*` endpoints require API key in production
- **Constant-time Comparison**: Prevents timing attacks on signature verification

### Input Protection
- **Input Sanitization**: All inputs sanitized via `sanitize_input()` utility
- **Pydantic Validation**: Request bodies validated with strict schemas
- **SQL Injection Prevention**: Table names validated via allowlists, all queries parameterized

### Resource Protection
- **Rate Limiting**: User queries limited to 20/hour, meetings to 5/hour
- **Bounded Caches**: All in-memory caches have size limits with LRU eviction
- **Circuit Breakers**: External API failures trigger circuit breakers to prevent cascades
- **Graceful Shutdown**: SIGTERM/SIGINT handlers ensure clean shutdown

### Infrastructure
- **Non-root Container**: Docker runs as non-root user
- **Security Headers**: HSTS, X-Frame-Options, X-Content-Type-Options
- **HTTPS Enforcement**: Production requires HTTPS (configurable)
- **No Secrets in Logs**: Tokens are never logged; sensitive data redacted

### Compliance
- **Audit Logging**: All sensitive operations logged to dedicated audit table
- **Data Sanitization**: Passwords, tokens, API keys auto-redacted in audit logs
- **Export Capability**: Audit logs exportable as JSON/CSV for compliance

## Versioning

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR**: Breaking API or configuration changes
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, security patches

### Getting a Specific Version

```bash
# List available versions
git tag -l

# Checkout a specific version
git checkout v1.0.0

# Pull and build a specific version
git fetch --tags
git checkout v1.0.0
docker-compose up -d --build
```

## License

Internal use only - Cloud Warriors

## Support

For issues, contact the development team or run `escalate` in the chat bot.
