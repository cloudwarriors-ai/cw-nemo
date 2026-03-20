# CODE_INDEX.md

Comprehensive code index for the QA Continuity App. This document provides a detailed map of all modules, classes, functions, and their relationships.

**Version:** 1.0.0
**Last Updated:** 2025-01-13
**Total Files:** 70+ Python modules
**Test Coverage:** 600+ tests

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Core Application Layer](#core-application-layer)
3. [Service Layer](#service-layer)
4. [Intelligence Layer](#intelligence-layer)
5. [Channel Layer](#channel-layer)
6. [Meeting Layer](#meeting-layer)
7. [Voice Layer](#voice-layer)
8. [Avatar Layer](#avatar-layer)
9. [Platform Layer](#platform-layer)
10. [Database Schema](#database-schema)
11. [API Routes](#api-routes)
12. [External Services](#external-services)
13. [Test Structure](#test-structure)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           PRESENTATION LAYER                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ Zoom Routes │  │Meeting Routes│  │ Voice Routes│  │Avatar Routes│    │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │
└─────────┼────────────────┼────────────────┼────────────────┼────────────┘
          │                │                │                │
┌─────────▼────────────────▼────────────────▼────────────────▼────────────┐
│                           SERVICE LAYER                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐│
│  │ AuthService  │  │ QueryService │  │RateLimitSvc  │  │WorkflowOrch  ││
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘│
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐│
│  │ConversationFlow│ │ReportService│  │HygieneService│  │FeedbackSvc   ││
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
          │                │                │                │
┌─────────▼────────────────▼────────────────▼────────────────▼────────────┐
│                         INTELLIGENCE LAYER                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐│
│  │   QABrain    │  │ QueryParser  │  │  IssueCache  │  │ResponseBuilder│
│  │  (LLM/NLU)   │  │  (Keywords)  │  │  (GitHub)    │  │  (Format)    ││
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
          │                │                │                │
┌─────────▼────────────────▼────────────────▼────────────────▼────────────┐
│                         INTEGRATION LAYER                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐│
│  │ GitHubClient │  │ ZoomChatbot  │  │ RecallClient │  │  N8nClient   ││
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘│
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐│
│  │VoicePipeline │  │ SimliClient  │  │LiveKitManager│  │  TTSClient   ││
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
          │
┌─────────▼───────────────────────────────────────────────────────────────┐
│                           DATA LAYER                                     │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    SQLite Database (database.py)                  │  │
│  │  Tables: interns, tasks, escalations, conversations, query_log,  │  │
│  │          meetings, transcripts, workflow_executions, audit_log   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Zoom Webhook → AuthService (HMAC) → QueryService → QABrain/QueryParser
    → IssueCache → ResponseBuilder → ZoomChatbot.send_message()

Meeting Join → RecallClient → MeetingHandler → TranscriptionProcessor
    → WakeWordDetector → VoicePipeline → SimliClient (Avatar)
```

---

## Core Application Layer

### src/bot/app.py
**Purpose:** Flask application factory and main webhook handler

| Function | Description |
|----------|-------------|
| `create_app(config)` | Application factory - initializes all components |
| `_handle_zoom_challenge()` | Handles Zoom URL validation |
| `_sanitize_input()` | Sanitizes user input (truncation, mention stripping) |
| `_verify_zoom_request()` | HMAC signature verification |
| `_process_query()` | Routes query to LLM or keyword parser |
| `_handle_onboarding_request()` | Triggers n8n onboarding workflow |
| `_handle_offboarding_request()` | Triggers n8n offboarding workflow |
| `_handle_intern_status_request()` | Retrieves intern status |
| `_handle_meeting_join_request()` | Handles meeting join requests |
| `_handle_weekly_report_request()` | Generates weekly reports |

**Dependencies:** All major components (see architecture diagram)

---

### src/bot/config.py
**Purpose:** Centralized configuration with environment variable support

| Class | Description |
|-------|-------------|
| `LLMConfig` | OpenRouter/Claude settings (model, timeout, max_tokens) |
| `CacheConfig` | Issue cache TTL and limits |
| `RateLimitConfig` | Chat (20/hr) and meeting (5/hr) limits |
| `InputSanitizationConfig` | Max length, mention patterns |
| `CircuitBreakerConfig` | Failure threshold, recovery timeout |
| `AuthorizationConfig` | Authorized users, allowed email domains |
| `OnboardingConfig` | Recurring meetings, documentation links |
| `Config` | Master configuration object |

| Function | Description |
|----------|-------------|
| `get_config()` | Thread-safe singleton config getter |
| `reset_config()` | Reset config (for testing) |

---

### src/bot/errors.py
**Purpose:** Standardized error handling

| Class | Description |
|-------|-------------|
| `ErrorCode` (Enum) | VALIDATION_ERROR, AUTH_ERROR, RATE_LIMIT, NOT_FOUND, etc. |
| `ApiError` | Error dataclass with JSON serialization |

| Function | Description |
|----------|-------------|
| `error_response(code, message, details)` | Create error response tuple |
| `success_response(data, message)` | Create success response tuple |
| `get_user_friendly_message(code)` | Map error codes to friendly messages |

---

### src/bot/database.py
**Purpose:** SQLite operations for all data persistence

| Class | Description |
|-------|-------------|
| `AsyncDatabaseWriter` | Non-blocking writes via background thread |
| `WriteOperation` | Queued write operation dataclass |

**Key Functions (60+):**

| Category | Functions |
|----------|-----------|
| **Init** | `init_db()`, `run_migrations()` |
| **Interns** | `get_intern_status()`, `add_intern()`, `update_intern_status()`, `get_intern_by_name()`, `get_intern_by_email()`, `get_all_interns()`, `get_interns_ending_soon()` |
| **Tasks** | `assign_task()`, `update_task_status()`, `get_intern_tasks()` |
| **Conversations** | `create_conversation_flow()`, `get_active_flow()`, `update_conversation_flow()`, `delete_conversation_flow()` |
| **Workflows** | `get_workflow_execution()`, `get_recent_executions()`, `update_workflow_execution()` |
| **Meetings** | `get_meeting_transcript()`, `save_transcript_segment()` |
| **Audit** | `log_audit_event()`, `get_audit_log()` |
| **Stats** | `get_query_stats()`, `log_query_async()` |

---

## Service Layer

### src/bot/services/auth_service.py
**Purpose:** Authentication and authorization

| Method | Description |
|--------|-------------|
| `verify_zoom_request(headers, body)` | Verify Zoom HMAC signature |
| `verify_recall_signature(headers, body)` | Verify Recall.ai Svix-style signature |
| `verify_api_key(headers)` | Verify API key for /api/* endpoints |
| `verify_n8n_callback(headers, data)` | Verify n8n callback |
| `can_manage_interns(user_id)` | Check role-based authorization |
| `validate_intern_email(email)` | Validate email domain |

---

### src/bot/services/query_service.py
**Purpose:** Core query processing orchestration

| Method | Description |
|--------|-------------|
| `sanitize_input(text)` | Remove mentions and sanitize |
| `process_query(text, user_id, context)` | Main query dispatcher |

---

### src/bot/services/rate_limit_service.py
**Purpose:** Rate limiting

| Method | Description |
|--------|-------------|
| `check_chat_limit(user_id)` | Check chat query limit (20/hour) |
| `check_meeting_limit(user_id)` | Check meeting join limit (5/hour) |
| `get_stats()` | Get rate limit statistics |

---

### src/bot/services/workflow_orchestrator.py
**Purpose:** Workflow coordination (Mediator Pattern)

| Method | Description |
|--------|-------------|
| `execute_weekly_report(channel)` | Generate and post weekly report |
| `execute_health_check(channel)` | Run hygiene checks |
| `execute_feedback_reminder(channel)` | Send intern feedback reminders |

---

### src/bot/services/conversation_flow.py
**Purpose:** Multi-turn onboarding/offboarding flows

| Class | Description |
|-------|-------------|
| `FlowStep` | Step definition (field, prompt, validation) |
| `FlowResponse` | Step response (message, is_complete) |
| `ConversationFlowHandler` | Flow state machine |

| Method | Description |
|--------|-------------|
| `start_onboarding_flow(user_id)` | Start onboarding conversation |
| `start_offboarding_flow(user_id)` | Start offboarding conversation |
| `handle_flow_input(user_id, input)` | Process user input in flow |

---

### src/bot/services/report_service.py
**Purpose:** Report generation

| Method | Description |
|--------|-------------|
| `generate_weekly_report()` | Generate weekly issue summary |

---

### src/bot/services/hygiene_service.py
**Purpose:** Issue health checks

| Method | Description |
|--------|-------------|
| `check_hygiene()` | Analyze issues for health problems |

---

### src/bot/services/feedback_service.py
**Purpose:** Feedback reminders

| Method | Description |
|--------|-------------|
| `send_weekly_reminder()` | Send intern progress reminder |

---

## Intelligence Layer

### src/bot/llm_brain.py
**Purpose:** LLM-powered natural language understanding (OpenRouter + Claude)

| Class | Description |
|-------|-------------|
| `Capability` (Enum) | ISSUE_QUERY, REPO_INFO, ONBOARDING, OFFBOARDING, MEETING_JOIN, INTERN_STATUS, WEEKLY_REPORT, ESCALATE, HELP, GENERAL, UNKNOWN |
| `ChatResponse` | Response with confidence, capability, filters |
| `WorkflowResponse` | Workflow decision with reasoning |
| `QABrain` | Main LLM brain service |

| Method | Description |
|--------|-------------|
| `chat_query(query, user_name, history)` | Process NL query with LLM |
| `workflow_decision(trigger, data)` | Make workflow decision |
| `generate_voice_response(data, query)` | Convert to conversational speech |
| `generate_meeting_summary(transcript)` | Summarize meeting transcript |
| `enhance_workflow_output(service, data)` | Format workflow output |

**Features:** Circuit breaker (5 failures → open), retry with backoff, sensitive topic detection

---

### src/bot/query_parser.py
**Purpose:** Keyword-based query parsing (LLM fallback)

| Class | Description |
|-------|-------------|
| `QueryType` (Enum) | HIGH_PRIORITY, UNASSIGNED, STALE, SUMMARY, REPO_FILTER, etc. |
| `QueryResult` | Parsed result with type, parameters, confidence |
| `QueryParser` | Keyword pattern matcher |

| Method | Description |
|--------|-------------|
| `parse(query)` | Parse query using 50+ keyword patterns |

---

### src/bot/cache.py
**Purpose:** SQLite-backed GitHub issue cache

| Class | Description |
|-------|-------------|
| `IssueCache` | GitHub issue caching service |

| Method | Description |
|--------|-------------|
| `get_issues()` | Get all cached issues |
| `get_filtered(repo, assignee, priority)` | Filter issues |
| `get_repo_issues(repo)` | Get issues for single repo |
| `get_stats()` | Get cache statistics |
| `refresh()` | Refresh from GitHub (manual only) |
| `invalidate()` | Clear cache |

---

### src/bot/circuit_breaker.py
**Purpose:** Circuit breaker pattern for resilience

| Class | Description |
|-------|-------------|
| `CircuitState` (Enum) | CLOSED, OPEN, HALF_OPEN |
| `CircuitBreaker` | Circuit breaker implementation |
| `CircuitOpenError` | Exception when circuit is open |

| Method | Description |
|--------|-------------|
| `can_execute()` | Check if request can proceed |
| `record_success()` | Record successful call |
| `record_failure()` | Record failed call |
| `get_status()` | Get current state and stats |

---

### src/bot/response_builder.py
**Purpose:** Format responses for Zoom Team Chat

| Method | Description |
|--------|-------------|
| `format_issue_list(issues, title)` | Format issues with markdown |
| `format_summary(stats)` | Format statistics |
| `format_help()` | Format help message |
| `format_intern_status(intern)` | Format intern details |

---

### src/bot/escalation.py
**Purpose:** Human escalation handling

| Method | Description |
|--------|-------------|
| `should_escalate(user_id, query)` | Check if escalation needed |
| `escalate(user_id, topic)` | Create escalation and notify |

---

### src/bot/n8n_client.py
**Purpose:** n8n workflow automation

| Class | Description |
|-------|-------------|
| `WorkflowType` (Enum) | ONBOARDING, OFFBOARDING, WEEKLY_FEEDBACK, HEALTH_CHECK |
| `WorkflowStatus` (Enum) | PENDING, RUNNING, COMPLETED, FAILED |
| `N8nClient` | n8n webhook client |

| Method | Description |
|--------|-------------|
| `trigger_onboarding(data)` | Start onboarding workflow |
| `trigger_offboarding(data)` | Start offboarding workflow |
| `trigger_weekly_feedback()` | Send feedback reminders |
| `trigger_health_check()` | Run hygiene checks |
| `get_execution(id)` | Get execution status |

---

### src/bot/prompts.py
**Purpose:** System prompts for LLM (versioned)

| Constant | Description |
|----------|-------------|
| `PROMPT_VERSION` | Version string ("1.0.0") |
| `CHAT_SYSTEM_PROMPT` | Chat bot instructions |
| `WORKFLOW_SYSTEM_PROMPT` | Workflow decision format |
| `ISSUE_QUERY_PROMPT` | Query classification |
| `MEETING_SUMMARY_PROMPT` | Meeting notes generation |
| `VOICE_RESPONSE_PROMPT` | Conversational voice conversion |
| `HELP_RESPONSE` | Help message content |
| `SENSITIVE_TOPICS` | Topics requiring escalation |

---

## Channel Layer

### src/bot/channels/base.py
**Purpose:** Abstract channel interface

| Class | Description |
|-------|-------------|
| `ChannelType` (Enum) | ZOOM, SLACK (future) |
| `Message` | Message dataclass |
| `DeliveryResult` | Delivery result dataclass |
| `Channel` (ABC) | Abstract channel interface |

---

### src/bot/channels/manager.py
**Purpose:** Multi-channel management

| Method | Description |
|--------|-------------|
| `register_adapter(type, adapter)` | Register channel adapter |
| `send_message(type, message)` | Send to specific channel |
| `send_to_all(message)` | Broadcast to all channels |

---

### src/bot/channels/zoom_adapter.py
**Purpose:** Zoom channel implementation

| Method | Description |
|--------|-------------|
| `send_message(message)` | Send via Zoom Chatbot API |
| `format_message(message)` | Format for Zoom markdown |

---

### src/zoom_chatbot.py
**Purpose:** Zoom Chatbot OAuth and messaging

| Method | Description |
|--------|-------------|
| `_get_access_token()` | Get OAuth token (cached) |
| `_get_admin_token()` | Get S2S admin token |
| `send_message(to_jid, message)` | Send channel message |
| `send_to_user(user_jid, message)` | Send direct message |

---

## Meeting Layer

### src/meeting/recall_client.py
**Purpose:** Recall.ai API client

| Class | Description |
|-------|-------------|
| `BotStatus` (Enum) | READY, JOINING, IN_CALL, RECORDING, DONE, ERROR |
| `RecallClient` | Recall.ai API client |

| Method | Description |
|--------|-------------|
| `join_meeting(url, bot_name)` | Request bot to join |
| `get_bot_status(bot_id)` | Get bot status |
| `get_transcript(bot_id)` | Get meeting transcript |
| `leave_meeting(bot_id)` | Bot leaves meeting |
| `delete_bot(bot_id)` | Delete bot instance |

---

### src/meeting/meeting_handler.py
**Purpose:** Meeting lifecycle management

| Method | Description |
|--------|-------------|
| `join_meeting(url, options)` | Request bot to join |
| `on_transcription_segment(segment)` | Process real-time transcription |
| `get_meeting_status(meeting_id)` | Get meeting status |
| `end_meeting(meeting_id)` | Process meeting completion |

---

### src/meeting/transcription.py
**Purpose:** Transcription processing

| Method | Description |
|--------|-------------|
| `process_segment(segment)` | Process transcription segment |
| `get_transcript(meeting_id)` | Get full transcript |
| `summarize_transcript(transcript)` | Generate summary |

---

### src/meeting/wake_word_detector.py
**Purpose:** Wake word detection

| Method | Description |
|--------|-------------|
| `contains_wake_word(text)` | Check for "QA Bot" or custom |
| `extract_command(text)` | Extract command after wake word |

---

## Voice Layer

### src/voice/voice_pipeline.py
**Purpose:** Full voice interaction pipeline (ASR → LLM → TTS)

| Class | Description |
|-------|-------------|
| `SemanticCache` | Query/response caching |
| `VoiceInteraction` | Interaction record |
| `VoicePipeline` | Main voice pipeline |

| Method | Description |
|--------|-------------|
| `process_audio(audio_data)` | Process audio chunks |
| `process_transcription(text, speaker)` | Process STT result |
| `respond_to_query(query)` | Get response and synthesize |

**Features:** Semantic caching (86% latency reduction), conversation history

---

### src/voice/speech_processor.py
**Purpose:** Audio processing

| Class | Description |
|-------|-------------|
| `VoiceActivityDetector` | VAD implementation |
| `SpeechProcessor` | Audio processor |

| Method | Description |
|--------|-------------|
| `detect_voice_activity(audio)` | Detect speech |
| `trim_silence(audio)` | Remove silence |
| `normalize_audio(audio)` | Normalize levels |

---

### src/voice/tts_client.py
**Purpose:** Text-to-speech

| Class | Description |
|-------|-------------|
| `TTSClient` (ABC) | Abstract TTS client |
| `CartesiaTTS` | Cartesia implementation |

| Method | Description |
|--------|-------------|
| `synthesize(text)` | Convert text to speech |
| `stream_audio(text)` | Stream audio chunks |

---

## Avatar Layer

### src/avatar/simli_client.py
**Purpose:** Simli avatar API client

| Class | Description |
|-------|-------------|
| `SimliSessionState` (Enum) | CREATED, CONNECTING, CONNECTED, STREAMING, CLOSED, ERROR |
| `SimliSession` | Session dataclass |
| `SimliClient` | Simli API client |

| Method | Description |
|--------|-------------|
| `create_session(face_id)` | Create avatar session |
| `send_audio(session_id, audio)` | Stream audio to avatar |
| `get_video_frame(session_id)` | Get video frame |
| `close_session(session_id)` | Close session |

---

### src/avatar/avatar_session.py
**Purpose:** Avatar session management

| Class | Description |
|-------|-------------|
| `AvatarMode` (Enum) | IDLE, LISTENING, THINKING, SPEAKING, ERROR |
| `AvatarState` | State dataclass |
| `AvatarSessionManager` | Session coordinator |

| Method | Description |
|--------|-------------|
| `start_session(meeting_id)` | Start avatar |
| `send_audio_for_avatar(audio)` | Process audio |
| `set_listening()` | Set listening state |
| `set_speaking()` | Set speaking state |
| `stop_session()` | Close session |

---

## Platform Layer

### src/github_client.py
**Purpose:** GitHub API wrapper

| Class | Description |
|-------|-------------|
| `Issue` | Issue dataclass |
| `GitHubClient` | GitHub API client |

| Method | Description |
|--------|-------------|
| `fetch_issues(repos)` | Fetch from multiple repos |
| `_extract_label_value(labels, prefix)` | Extract label values |
| `_is_stale(updated_at)` | Check if stale (14+ days) |

---

### src/zoom_notifier.py
**Purpose:** Zoom notifications

| Method | Description |
|--------|-------------|
| `notify(user_id, message)` | Send direct message |
| `notify_channel(channel_id, message)` | Send channel message |

---

### src/zoom_meetings.py
**Purpose:** Zoom Meetings API (S2S OAuth)

| Method | Description |
|--------|-------------|
| `add_registrant(meeting_id, email, name)` | Add user to meeting |
| `remove_registrant(meeting_id, registrant_id)` | Remove from meeting |
| `get_meeting_info(meeting_id)` | Get meeting details |

---

## Database Schema

```sql
-- Core Tables
interns (id, name, email, program, status, supervisor, start_date, end_date, github_username)
tasks (id, intern_id, title, github_issue, status, created_at)
escalations (id, user_id, topic, status, created_at, resolved_at)

-- Conversation & Flow
conversations (id, user_id, context, last_query, updated_at)
conversation_flows (id, flow_id, user_id, flow_type, current_step, collected_data, expires_at)

-- Rate Limiting
rate_limits (id, user_id, timestamp)
meeting_rate_limits (id, user_id, timestamp)

-- Meetings & Transcription
meetings (id, bot_id, meeting_url, status, created_at, ended_at)
transcripts (id, meeting_id, full_text, created_at)
transcript_segments (id, meeting_id, speaker, text, start_time, end_time)

-- Workflow & Audit
workflow_executions (id, workflow_type, status, input_data, result, created_at)
audit_log (id, action, target_type, target_id, actor_user_id, details, created_at)

-- Caching
issue_cache (id, repo, issue_number, title, assignee, priority, labels, is_stale, updated_at)
cache_metadata (id, key, value, updated_at)
query_log (id, user_id, query_type, response_time_ms, success, created_at)
```

---

## API Routes

### Health & Status
| Route | Method | Description | Auth |
|-------|--------|-------------|------|
| `/health` | GET | Basic health check | None |
| `/health?detailed=true` | GET | Full dependency check | None |

### Zoom Integration
| Route | Method | Description | Auth |
|-------|--------|-------------|------|
| `/zoom/webhook` | POST | Team Chat webhook | HMAC |
| `/api/query` | POST | Direct API query | API Key |
| `/api/zoom/send` | POST | Send message | API Key |
| `/api/cache/refresh` | POST | Refresh issue cache | API Key |
| `/api/stats` | GET | Query statistics | API Key |

### Meetings
| Route | Method | Description | Auth |
|-------|--------|-------------|------|
| `/api/meeting/join` | POST | Join meeting | API Key |
| `/meetings/webhook` | POST | Recall.ai webhook | HMAC |
| `/api/meeting/<id>` | GET | Meeting status | API Key |
| `/api/meeting/<id>/transcript` | GET | Get transcript | API Key |

### Voice
| Route | Method | Description | Auth |
|-------|--------|-------------|------|
| `/api/voice/status` | GET | Voice pipeline status | API Key |
| `/voice/transcription` | POST | Transcription webhook | HMAC |

### Avatar
| Route | Method | Description | Auth |
|-------|--------|-------------|------|
| `/api/avatar/status` | GET | Avatar status | API Key |
| `/api/avatar/start` | POST | Start avatar | API Key |
| `/api/avatar/stop` | POST | Stop avatar | API Key |
| `/avatar/page` | GET | Avatar webpage | None |

### GitHub
| Route | Method | Description | Auth |
|-------|--------|-------------|------|
| `/github/webhook` | POST | GitHub webhook | HMAC |

---

## External Services

| Service | Module | Purpose | Rate Limit |
|---------|--------|---------|------------|
| **GitHub API** | `github_client.py` | Issue fetching | 5,000/hr |
| **OpenRouter** | `llm_brain.py` | LLM queries (Claude) | Per plan |
| **Zoom Team Chat** | `zoom_chatbot.py` | Messaging | Unlimited |
| **Zoom Meetings** | `zoom_meetings.py` | Meeting management | Unlimited |
| **Recall.ai** | `recall_client.py` | Meeting bot | 3/session |
| **n8n** | `n8n_client.py` | Workflow automation | Unlimited |
| **Simli** | `simli_client.py` | Avatar generation | 2/session |
| **Cartesia** | `tts_client.py` | Text-to-speech | 3/session |
| **OpenAI** | `voice_pipeline.py` | ASR/TTS fallback | 5/session |
| **Deepgram** | `speech_processor.py` | Streaming STT | 3/session |
| **LiveKit** | `livekit_manager.py` | WebRTC video | 5/session |

---

## Test Structure

```
tests/
├── conftest.py                    # Shared fixtures
├── test_app.py                    # Flask app tests
├── test_query_parser.py           # Query parsing
├── test_llm_brain.py              # LLM integration
├── test_config.py                 # Configuration
├── test_errors.py                 # Error handling
├── test_circuit_breaker.py        # Circuit breaker
├── test_database.py               # Database operations
├── test_channels.py               # Channel abstraction
├── test_conversation_flow.py      # Onboarding/offboarding
├── test_services.py               # Service layer
├── test_voice.py                  # Voice pipeline
├── test_avatar.py                 # Avatar integration
├── test_meeting.py                # Meeting handler
├── test_recall_webhook_auth.py    # Recall.ai auth (11 tests)
└── integration/
    ├── conftest.py                # Integration fixtures
    ├── test_github_integration.py
    ├── test_recall_integration.py
    ├── test_avatar_integration.py
    └── test_voice_integration.py
```

### Key Fixtures (conftest.py)
| Fixture | Description |
|---------|-------------|
| `temp_db` | Temporary SQLite database |
| `app` | Flask test application |
| `client` | Flask test client |
| `sample_issues` | Sample Issue objects |

---

## Design Patterns Used

| Pattern | Location | Purpose |
|---------|----------|---------|
| **Application Factory** | `app.py:create_app()` | Flask app initialization |
| **Circuit Breaker** | `circuit_breaker.py` | External API resilience |
| **Mediator** | `WorkflowOrchestrator` | Service coordination |
| **Repository** | `database.py` | Data access isolation |
| **Service Layer** | `services/` | Business logic separation |
| **Channel Abstraction** | `channels/` | Multi-channel support |
| **State Machine** | `ConversationFlowHandler` | Multi-turn flows |
| **Semantic Cache** | `VoicePipeline` | Response caching |

---

## Security Features

| Feature | Location | Description |
|---------|----------|-------------|
| HMAC Verification | `auth_service.py` | Zoom/Recall webhook auth |
| API Key Auth | `auth_service.py` | /api/* endpoint protection |
| Rate Limiting | `rate_limit_service.py` | 20/hr chat, 5/hr meetings |
| Input Sanitization | `app.py` | Truncation, mention stripping |
| Role-Based Access | `auth_service.py` | Intern management authorization |
| Audit Logging | `database.py` | Compliance trail |
| Message Dedup | `app.py` | Prevent duplicate processing |
| Sensitive Topics | `query_parser.py` | Auto-escalation |
