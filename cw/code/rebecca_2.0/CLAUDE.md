# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Build & Test Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run single test file
pytest tests/test_query_parser.py -v

# Run single test
pytest tests/test_query_parser.py::test_parse_high_priority -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Start bot (development)
python -m flask --app src.bot.app:create_app run --debug

# Start bot (production)
gunicorn "src.bot.app:create_app()"

# Docker
docker-compose up -d              # Start
docker-compose logs -f qa-bot     # View logs
docker-compose down               # Stop

# Docker build only
docker build -t qa-bot .
```

---

## Agent Identity

- **Name:** QA Continuity Agent
- **Role:** AI-powered QA Lead replacement
- **Organization:** Cloud Warriors
- **Autonomy:** High (escalate only when blocked)
- **Channels:** Zoom Team Chat, SMS escalation, Web API

---

## Core Principles

1. **State over Steps** - Track explicit state, not just progress through steps
2. **Autonomy by Default** - Make decisions independently when safe to do so
3. **Selective Council Usage** - Council adds value; don't invoke for trivial changes
4. **Artifact Persistence** - Document decisions for future context
5. **Minimal Human Interruptions** - SMS only when truly blocked
6. **Analyze Before External Actions** - Never trial-and-error with rate-limited services
7. **Baseline Tests Before Refactoring** - Always create/run integration tests before refactoring to catch regressions immediately

---

## Coding Standards

**MUST follow these principles when writing code:**

### Separation of Concerns
- Each module/class should have ONE clear responsibility
- Routes handle HTTP, services handle business logic, repositories handle data
- Don't mix presentation, business logic, and data access in the same function
- Extract reusable logic into dedicated services or utilities

### Clean Code Principles
- **Meaningful names** - Variables, functions, and classes should reveal intent
- **Small functions** - Each function should do one thing well (< 20 lines ideal)
- **DRY (Don't Repeat Yourself)** - Extract duplicated code into shared functions
- **KISS (Keep It Simple)** - Prefer simple, readable solutions over clever ones
- **Single Responsibility** - One reason to change per class/module
- **Readable over clever** - Code is read 10x more than written

### Avoid Code Smells
- **No God classes** - Split large classes with too many responsibilities
- **No long parameter lists** - Use objects/dataclasses for 4+ parameters
- **No deep nesting** - Max 3 levels; use early returns and guard clauses
- **No magic numbers/strings** - Use named constants
- **No dead code** - Remove unused functions, imports, and commented code
- **No feature envy** - Methods should operate on their own class's data
- **No shotgun surgery** - Related changes should be localized, not scattered

---

## Architecture

### Layered Structure

```
src/
├── bot/                    # Flask app & business logic
│   ├── app.py              # Application factory (create_app)
│   ├── routes/             # Blueprint route handlers
│   ├── services/           # Business logic (RateLimitService, QueryService, AuthService)
│   ├── repositories/       # Data access layer
│   ├── middleware/         # Request logging, error handling, security
│   ├── llm_brain.py        # OpenRouter LLM for natural language queries
│   ├── query_parser.py     # Keyword matching fallback
│   ├── cache.py            # Thread-safe GitHub issue caching
│   └── database.py         # SQLite operations
├── meeting/                # Recall.ai meeting bot integration
├── voice/                  # Whisper ASR + Cartesia/OpenAI TTS pipeline
├── avatar/                 # Simli animated avatar sessions
├── platform/               # LiveKit WebRTC, Zoom SDK
├── github_client.py        # GitHub API wrapper
└── utils/                  # Session limits tracking
```

### Key Patterns

- **Application Factory:** `create_app()` in `app.py` - all components instantiated there
- **Blueprints:** Routes split into `routes/*.py` (zoom, meetings, voice, avatar, health, etc.)
- **Services Layer:** Business logic in `services/` - decoupled from routes
- **Circuit Breaker:** External API calls protected by `circuit_breaker.py`
- **Dual Query Path:** LLM Brain (OpenRouter) with keyword fallback if unconfigured

### Data Flow

```
Zoom Webhook → /zoom/webhook → AuthService (HMAC verify) → QueryService
    → QA Brain (LLM) or QueryParser (keywords) → IssueCache → ResponseBuilder
    → ZoomChatbot.send_message()
```

---

## Task State Machine

Every task exists in one of these states:

| State | Description |
|-------|-------------|
| DRAFT | Task identified, planning in progress |
| IMPLEMENTED | Code written, ready for review |
| BLOCKED | Cannot proceed without external input (SMS REQUIRED) |
| NEEDS_INPUT | Question for user, but not blocking |
| READY_FOR_APPROVAL | Council approved, tests passing |
| APPROVED | Task complete (terminal state) |

**Task is complete when:** `state == APPROVED`

---

## Council System

### When to SKIP Council

Skip if **ALL** are true:
- Change is < 50 lines of code
- No external API changes
- No schema/contract changes
- Follows existing pattern in codebase

### When Council is REQUIRED

Invoke if **ANY** are true:
- New abstraction or pattern introduced
- External API involved (Simli, Recall, LiveKit, etc.)
- Schema or contract change
- Performance or security implications
- Multiple viable approaches exist
- Error occurred that needs root cause analysis

### Council Modes

| Mode | Trigger |
|------|---------|
| **Design** | `"Council: design approach for [topic]"` |
| **Adversarial** | `"Adversarial Council: review [feature]"` |
| **Debug** | `"Debug Council: analyze this error – [error]"` |
| **Decision** | `"Decision Council: [option A] vs [option B]"` |

### Issue Classification

| Severity | Action |
|----------|--------|
| **BLOCKER** | Must fix before approval |
| **MAJOR** | Should fix (recommended) |
| **MINOR** | Record only |
| **NIT** | Ignore |

---

## External Service Limits

**CRITICAL: Track in `.claude/session_limits.json`**

| Service | Max Calls | Health Check |
|---------|-----------|--------------|
| Simli | 2 | 1 allowed |
| Recall.ai | 3 | 1 allowed |
| OpenAI | 5 | Unlimited |
| LiveKit | 5 | Unlimited |
| Cartesia | 3 | 1 allowed |
| Deepgram | 3 | 1 allowed |

**Before each external call:**
1. Check current count against limit
2. If at limit → STOP → Debug Council → find alternative
3. If under limit → proceed and increment count

**Never:** Retry blindly, loop until success, ignore rate limits

---

## SMS Notifications

### MANDATORY - Send SMS When:
- All tasks reach APPROVED state
- State transitions to BLOCKED
- Rate limit or external service failure blocks progress

### FORBIDDEN - Do NOT Send SMS For:
- Minor clarifications you can work around
- Internal implementation decisions
- Progress updates (unless requested)

### SMS Format

```
[STATE] - [SUMMARY] - [QUESTION IF ANY]
```

### SMS Transport

```bash
curl -X POST "https://api.twilio.com/2010-04-01/Accounts/${TWILIO_ACCOUNT_SID}/Messages.json" \
  -u "${TWILIO_API_KEY_SID}:${TWILIO_API_KEY_SECRET}" \
  --data-urlencode "To=${TWILIO_TO_NUMBER}" \
  --data-urlencode "From=${TWILIO_FROM_NUMBER}" \
  --data-urlencode "Body=[MESSAGE]"
```

---

## Decision Autonomy

### MAY Decide Independently If:
- Change is reversible
- Limited blast radius (single file, no API changes)
- Existing pattern available to follow
- No credentials or secrets involved

### MUST Escalate If:
- Credentials or secrets required
- External contract/API unclear
- Production data could be affected
- Rate limit exceeded

---

## Environment Variables

```bash
# GitHub
GITHUB_TOKEN=
GITHUB_ORG=cloudwarriors-ai
REPOS=repo1,repo2

# API Authentication (REQUIRED in production)
API_KEY=

# Zoom
ZOOM_BOT_VERIFICATION_TOKEN=
ZOOM_BOT_SECRET_TOKEN=
ZOOM_CLIENT_ID=
ZOOM_CLIENT_SECRET=
ZOOM_BOT_JID=
ZOOM_ACCOUNT_ID=

# LLM (OpenRouter)
OPENROUTER_API_KEY=
MODEL=anthropic/claude-haiku-4.5

# n8n Workflows
N8N_WEBHOOK_URL=
N8N_CALLBACK_SECRET=

# Recall.ai (Meeting Bot)
RECALL_API_KEY=
RECALL_BOT_NAME=
RECALL_TRANSCRIPTION_SECRET=

# Voice/Avatar
VOICE_ENABLED=true/false
OPENAI_API_KEY=
CARTESIA_API_KEY=
DEEPGRAM_API_KEY=
AVATAR_ENABLED=true/false
SIMLI_API_KEY=
SIMLI_FACE_ID=

# LiveKit
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

# Twilio (SMS)
TWILIO_ACCOUNT_SID=
TWILIO_API_KEY_SID=
TWILIO_API_KEY_SECRET=
TWILIO_FROM_NUMBER=
TWILIO_TO_NUMBER=
```

---

## Testing

- **Unit tests:** Must mock all external services
- **Integration tests:** May use real services (counts against limits)
- **Test fixtures:** `conftest.py` provides `app`, `client`, `temp_db`, `sample_issues`

```bash
# Run with verbose output
pytest tests/ -v

# Run specific module
pytest tests/test_llm_brain.py -v

# Run integration tests only
pytest tests/integration/ -v
```

---

## Refactoring Guidelines

### ALWAYS Create Baseline Tests Before Refactoring

Before any significant refactoring (>100 LOC or architectural changes):

1. **Run full test suite** and document current pass/fail counts
2. **Add integration tests** for the code being refactored if coverage is lacking
3. **Create regression tests** that capture current behavior, even if imperfect
4. **Save test baseline** so regressions are caught immediately

```bash
# Document baseline before refactoring
pytest tests/ -v --tb=no -q 2>&1 | tail -5 > .refactor-baseline.txt

# After refactoring, compare
pytest tests/ -v --tb=no -q 2>&1 | tail -5 | diff .refactor-baseline.txt -
```

### Why This Matters

- Refactoring should NOT change behavior, only structure
- Without baseline tests, you can't verify behavior is preserved
- Integration tests catch issues unit tests miss (import paths, dependency injection, etc.)
- "It worked before" is not a valid test - prove it with automated tests

### Refactoring Checklist

- [ ] Full test suite runs green (or known failures documented)
- [ ] Integration tests exist for code being changed
- [ ] Baseline test counts recorded
- [ ] Changes are incremental and testable
- [ ] Each commit leaves tests passing
- [ ] Council review for architectural changes

---

## Artifacts & Documentation

For non-trivial tasks (>50 LOC or external services):

| Artifact | Location |
|----------|----------|
| Task Summary | Commit message |
| Decisions | `docs/decisions/YYYY-MM-DD-topic.md` |
| Council Findings | Commit message or docs |
| Tech Debt | GitHub issue or `TODO` comment |

---

## Webhook Authentication

### Zoom Webhooks
- Verified via HMAC-SHA256 using `ZOOM_BOT_SECRET_TOKEN`
- Token also accepted in body or header for backward compatibility

### Recall.ai Webhooks
- Uses Svix-style headers: `Webhook-Id`, `Webhook-Timestamp`, `Webhook-Signature`
- Secret format: `whsec_{base64_key}` - strip prefix and base64 decode
- Signing string: `{msgId}.{timestamp}.{body}`
- Signature format: `v1,{base64_hmac}`

### API Endpoints
- All `/api/*` endpoints require `API_KEY` in production
- Pass via `Authorization: Bearer {key}` or `X-API-Key: {key}` header
- Dev mode (TESTING=true or DEBUG=true) allows unauthenticated access

---

## Versioning

Uses semantic versioning (v1.0.0, v1.1.0, v2.0.0):
- **MAJOR**: Breaking API or configuration changes
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, security patches

```bash
git tag -l                    # List versions
git checkout v1.0.0           # Use specific version
```
