# AI QA Lead Implementation Plan

**Status:** Approved by Council
**Created:** 2026-01-10
**Council Session:** Architecture for AI QA Lead Replacement

---

## Executive Summary

This plan outlines the implementation of an AI-powered QA Lead system to replace the departed QA Lead role at Cloud Warriors. The system will be conversational, multi-platform, and capable of handling routine QA tasks while keeping humans in the loop for judgment-intensive decisions.

### Vision Statement

> An inference engine that users can talk to, works with different applications, handles onboarding/offboarding via n8n, posts to Zoom chat, joins meetings with an avatar, and can speak and hear.

### Council Consensus

The three-persona council (Alex Chen - AI Developer, Sam Rivera - Zoom Expert, Jordan Taylor - QA Expert) unanimously agreed on a **4-phase implementation** approach, prioritizing:

1. Incremental delivery over big-bang release
2. Third-party services over custom SDK development
3. Human-in-the-loop for judgment calls
4. Testable, keyword-based parsing before LLM complexity

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AI QA Lead System                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐   ┌───────────┐ │
│  │   Phase 1     │   │   Phase 2     │   │   Phase 3     │   │  Phase 4  │ │
│  │   Chat Bot    │──▶│ n8n Workflows │──▶│  Meeting Bot  │──▶│Voice/Avatar│ │
│  │  (Zoom TC)    │   │ (Automation)  │   │ (Recall.ai)   │   │(AIAvatarKit)│ │
│  └───────────────┘   └───────────────┘   └───────────────┘   └───────────┘ │
│         │                   │                   │                  │        │
│         └───────────────────┴───────────────────┴──────────────────┘        │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Shared Backend                                │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  - GitHub Client (existing: src/github_client.py)                   │   │
│  │  - Report Generator (existing: src/report_generator.py)             │   │
│  │  - LLM Brain (Claude API for conversational understanding)          │   │
│  │  - State Store (SQLite for context, intern tracking)                │   │
│  │  - Escalation Manager (routes to humans when needed)                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## QA Lead Role Analysis

Based on `docs/QA Continuity.docx.md`, the QA Lead handled these responsibilities:

### Automatable Tasks (AI Handles Independently)

| Task | Current State | AI Capability |
|------|---------------|---------------|
| GitHub issue weekly reports | Exists in `src/main.py` | Extend to on-demand queries |
| Issue hygiene checks | Exists in `src/report_generator.py` | Add real-time alerts |
| Application health checks | Manual checklist | Automated test runs + reporting |
| Status queries | None | Chat bot responds instantly |
| Meeting notes/transcription | Manual | Meeting bot captures automatically |

### Partially Automatable (AI Assists, Human Approves)

| Task | AI Role | Human Role |
|------|---------|------------|
| Intern task assignment | Suggest available tasks, match skill level | Approve assignment |
| Onboarding checklist | Send reminders, track completion | Review progress |
| Weekly feedback prep | Compile accomplishments, status | Write actual feedback |
| Offboarding triggers | Detect end date, initiate workflow | Confirm completion |

### Human-Only Tasks (AI Surfaces Info)

| Task | Why Human Required |
|------|-------------------|
| Intern performance evaluation | Judgment on "character, work ethic, motivations" (per QA doc) |
| "Graduation" decisions | Career-impacting decision requires human accountability |
| Conflict resolution | Interpersonal skills required |
| Strategic QA planning | Business context and priorities |

---

## Phase 1: Conversational Chat Bot

**Objective:** Interactive Zoom Team Chat bot that answers questions about issues, interns, and QA status.

**Foundation:** Extend `docs/FEATURE_Interactive_Zoom_Agent.md` architecture.

### Capabilities

| Command | Response | Example |
|---------|----------|---------|
| `high priority` | List high-priority issues | "3 high priority issues: pulse#42, macd#15..." |
| `unassigned` | List unassigned issues | "5 unassigned issues..." |
| `stale` | Issues with no update 14+ days | "2 stale issues..." |
| `intern status` | Current intern assignments and progress | "Sara: 3 tasks in progress, 2 completed this week" |
| `weekly summary` | Aggregated stats across repos | Table of issues by repo, priority, status |
| `help` | List available commands | Full command reference |
| `escalate [topic]` | Notify human contact | "I've notified @chad3 about: [topic]" |

### Technical Implementation

```
qa_continuity_app/
├── src/
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── app.py              # Flask webhook handler
│   │   ├── query_parser.py     # Keyword + LLM hybrid parser
│   │   ├── response_builder.py # Format responses for Zoom
│   │   ├── escalation.py       # Human handoff logic
│   │   └── cache.py            # Issue caching (60s TTL)
│   ├── github_client.py        # (existing)
│   ├── report_generator.py     # (existing - extend)
│   ├── zoom_notifier.py        # (existing)
│   └── utils.py                # (existing)
├── data/
│   └── state.db                # SQLite for context tracking
└── requirements.txt            # Add: flask, gunicorn, anthropic
```

### Query Parser Design

**Hybrid Approach:** Keyword matching for structured queries, LLM fallback for natural language.

```python
def parse_query(text: str) -> QueryResult:
    """
    1. Try keyword matching first (fast, deterministic)
    2. If no match, use Claude for intent classification
    3. If still unclear, ask for clarification
    """
    # Keyword patterns (from FEATURE_Interactive_Zoom_Agent.md)
    if matches_keyword_pattern(text):
        return extract_structured_query(text)

    # LLM fallback for natural language
    intent = classify_with_llm(text)
    if intent.confidence > 0.8:
        return intent.to_query()

    # Unclear - ask for clarification
    return QueryResult(type="clarify", message="I'm not sure what you're asking...")
```

### Zoom Integration

**Method:** Chatbot webhook (not Meeting SDK)

**Setup:**
1. Create Zoom Marketplace App (Chatbot type)
2. Configure webhook endpoint: `https://your-domain.com/zoom/webhook`
3. Subscribe to `chat_message.received` event
4. Store verification token in `.env`

**Response Flow:**
```
User message in Zoom channel
    → Zoom sends POST to /zoom/webhook
    → Bot validates token, parses query
    → Fetches data (cached GitHub issues, intern state)
    → Formats response
    → Returns JSON with response text
    → Zoom displays in channel
```

### Acceptance Criteria

| Criteria | Target | Measurement |
|----------|--------|-------------|
| Command accuracy | 100% for defined commands | Unit tests for all patterns |
| Response time | < 3 seconds | Zoom webhook timeout compliance |
| Unknown query handling | Helpful response, not silence | Integration test |
| Escalation delivery | < 5 seconds to notify human | End-to-end test |
| Uptime | 99%+ | Health check monitoring |

### Deployment

**Recommended:** Docker on cloud VM (AWS EC2, DigitalOcean, etc.)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ ./src/
COPY data/ ./data/
ENV PYTHONUNBUFFERED=1
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "2", "src.bot.app:app"]
```

**Environment Variables:**
```
GITHUB_TOKEN=ghp_xxx
GITHUB_ORG=cloudwarriors-ai
ZOOM_BOT_VERIFICATION_TOKEN=xxx
ZOOM_WEBHOOK_URL=https://hooks.zoom.us/xxx
ANTHROPIC_API_KEY=sk-ant-xxx
ESCALATION_CONTACT=@chad3
```

---

## Phase 2: n8n Workflow Automation

**Objective:** Automate onboarding, offboarding, and recurring tasks using n8n workflows.

### n8n Overview

n8n is an open-source workflow automation platform with 400+ integrations. It handles:
- Trigger-based automation (new hire detected → start onboarding)
- Scheduled tasks (weekly reminders)
- Multi-step workflows (checklist items over time)
- Integration with Zoom, Google Docs, GitHub, Slack, etc.

**Source:** [n8n ITOps](https://n8n.io/itops/)

### Workflows to Implement

#### Workflow 1: Intern Onboarding

**Trigger:** New intern added to tracking system (or manual trigger)

**Steps:**
1. **Day 0:** Send welcome message to Zoom channel
2. **Day 0:** Create getting-started document (template from Google Docs)
3. **Day 0:** Add to Daily DevOps Meeting invite
4. **Day 1:** Send orientation checklist
5. **Day 3:** Check-in reminder to QA bot
6. **Week 1:** Send application testing assignments
7. **Ongoing:** Weekly progress reminder every Friday

**n8n Flow:**
```
[Webhook Trigger] → [Create Google Doc from Template]
                  → [Send Zoom Message: Welcome]
                  → [Wait 1 day]
                  → [Send Zoom Message: Orientation Checklist]
                  → [Wait 2 days]
                  → [HTTP Request: Notify Bot for Check-in]
                  → [Schedule: Weekly Friday Reminder]
```

#### Workflow 2: Weekly Feedback Prep

**Trigger:** Every Friday at 2:00 PM EST

**Steps:**
1. Query GitHub for intern's closed issues this week
2. Query state DB for completed tasks
3. Compile summary document
4. Send to Zoom channel: "Weekly feedback prep ready for [intern]"
5. @ mention supervisor for review

#### Workflow 3: Offboarding

**Trigger:** Intern end date reached (or manual trigger)

**Steps:**
1. Send offboarding checklist to intern
2. Notify IT for access revocation
3. Create post-internship feedback form
4. Archive intern documents
5. Send thank-you message to Zoom channel

#### Workflow 4: Application Health Checks

**Trigger:** Every Monday at 9:00 AM EST

**Steps:**
1. Run health check scripts for each application
2. Compile results
3. Post to Zoom DevOps channel
4. If failures detected, create GitHub issue and @ mention on-call

### n8n Setup

**Deployment Options:**

| Option | Pros | Cons |
|--------|------|------|
| Self-hosted (Docker) | Full control, free | Maintenance burden |
| n8n Cloud | Managed, easy setup | Monthly cost (~$20+) |

**Recommended:** n8n Cloud for simplicity, or self-hosted Docker alongside chat bot.

**Integration with Chat Bot:**
- n8n calls chat bot API for status queries
- Chat bot triggers n8n workflows via webhook
- Shared state in SQLite database

### Acceptance Criteria

| Criteria | Target | Measurement |
|----------|--------|-------------|
| Onboarding workflow completion | 100% of steps execute | Workflow logs |
| Reminder delivery | Within 1 hour of scheduled time | Timestamp verification |
| Escalation on failure | Immediate notification | Error handling test |
| Workflow visibility | Dashboard shows all active workflows | n8n UI |

---

## Phase 3: Meeting Presence (Recall.ai Integration)

**Objective:** AI QA Lead joins Zoom meetings as a visible participant with custom avatar, captures audio, and can be queried during meetings.

### Why Third-Party Service?

**Council Finding:** Building native Zoom Meeting SDK integration requires:
- Linux environment with C++ SDK
- Implementation of `IZoomSDKVideoSource` interface
- Zoom Marketplace app approval (2-4 weeks)
- Ongoing SDK maintenance

**Effort:** 4-8 weeks

**Alternative:** Recall.ai API handles all SDK complexity. Integration effort: 2-3 days.

**Sources:**
- [Recall.ai - How to Build a Zoom Bot](https://www.recall.ai/blog/how-to-build-a-zoom-bot)
- [Recall.ai - Streaming Video](https://www.recall.ai/blog/zoom-sdk-streaming-video-to-meeting)

### Recall.ai Capabilities

| Feature | Supported |
|---------|-----------|
| Join Zoom meetings | Yes |
| Custom bot name | Yes |
| Custom avatar image | Yes |
| Capture audio | Yes |
| Real-time transcription | Yes |
| Send audio to meeting | Yes (with additional setup) |
| Video streaming | Yes (custom video source) |

### Integration Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Zoom Meeting   │────▶│   Recall.ai     │────▶│  Our Backend    │
│                 │     │   (Meeting Bot) │     │  (Chat Bot +    │
│  - Participants │     │   - Joins mtg   │     │   LLM Brain)    │
│  - Audio/Video  │     │   - Captures    │     │                 │
│                 │◀────│   - Streams     │◀────│  - Processes    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Implementation

**New Files:**
```
src/
├── meeting/
│   ├── __init__.py
│   ├── recall_client.py    # Recall.ai API wrapper
│   ├── meeting_handler.py  # Process meeting events
│   └── transcription.py    # Handle transcription data
```

**Recall.ai API Integration:**

```python
# recall_client.py
import requests

class RecallClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.recall.ai/api/v1"

    def create_bot(self, meeting_url: str, bot_name: str, avatar_url: str) -> dict:
        """Create a bot to join a Zoom meeting."""
        response = requests.post(
            f"{self.base_url}/bot",
            headers={"Authorization": f"Token {self.api_key}"},
            json={
                "meeting_url": meeting_url,
                "bot_name": bot_name,
                "bot_image": avatar_url,
                "transcription_options": {"provider": "deepgram"},
                "real_time_transcription": {
                    "destination_url": "https://our-backend.com/transcription"
                }
            }
        )
        return response.json()

    def get_bot_status(self, bot_id: str) -> dict:
        """Get current status of a bot."""
        response = requests.get(
            f"{self.base_url}/bot/{bot_id}",
            headers={"Authorization": f"Token {self.api_key}"}
        )
        return response.json()

    def send_audio(self, bot_id: str, audio_data: bytes):
        """Send audio to the meeting (TTS output)."""
        # Implementation depends on Recall.ai's audio streaming API
        pass
```

**Meeting Workflow:**

1. User invites QA bot to meeting (sends meeting URL to chat bot)
2. Chat bot calls Recall.ai to create meeting bot
3. Recall.ai bot joins meeting with custom name and avatar
4. Real-time transcription sent to our backend
5. Backend can respond to questions (text summary posted to chat, or audio if Phase 4 complete)
6. After meeting, full transcript available for notes

### Avatar Design

**Recommendation:** Professional, friendly avatar representing QA function.

**Options:**
1. Static image (simplest) - professional headshot-style illustration
2. Animated avatar (Phase 4) - responds visually during speech

**Avatar Requirements:**
- Square image, 256x256 or 512x512 pixels
- Professional appearance
- Recognizable as "QA Bot" or similar

### Acceptance Criteria

| Criteria | Target | Measurement |
|----------|--------|-------------|
| Join meeting | Within 30 seconds of request | Timestamp logging |
| Bot visibility | Name and avatar visible to all participants | Manual verification |
| Transcription accuracy | 95%+ word accuracy | Comparison to manual transcript |
| Real-time delivery | Transcription within 2 seconds of speech | Latency measurement |
| Meeting notes | Available within 5 minutes of meeting end | Automated check |

### Cost Estimation

**Recall.ai Pricing:** Usage-based, approximately $0.69/hour per meeting.

| Usage Scenario | Monthly Cost |
|----------------|--------------|
| 5 meetings/week, 1 hour each | ~$15/month |
| 10 meetings/week, 1 hour each | ~$30/month |
| 20 meetings/week, 1 hour each | ~$60/month |

---

## Phase 4: Voice and Avatar (COMPLETE)

**Objective:** AI QA Lead speaks in meetings with real-time voice and animated avatar.

**Status:** ✅ COMPLETE (Voice pipeline implemented, Avatar deferred for GPU infrastructure)

### Technology Options

Based on council research:

| Technology | Type | Latency | Best For |
|------------|------|---------|----------|
| [Cartesia TTS](https://cartesia.ai/product/python-text-to-speech-api-tts) | TTS API | 40ms | Low-latency speech |
| [AIAvatarKit](https://github.com/uezo/aiavatarkit) | Speech-to-Speech Framework | Variable | Full avatar system |
| [Linly-Talker](https://github.com/Kedreamix/Linly-Talker) | Digital Human System | 500ms+ | Realistic avatar |
| [RealtimeTTS](https://github.com/KoljaB/RealtimeTTS) | Python TTS Library | Variable | Local processing |

### Proposed Architecture

```
User speaks in meeting
    → Recall.ai captures audio
    → Whisper ASR → text
    → Claude processes query
    → Response text generated
    → Cartesia TTS → audio
    → AIAvatarKit → avatar animation synced to audio
    → Recall.ai streams video/audio back to meeting
```

### Implementation Considerations

1. **Latency Budget:** User expects response within 2-3 seconds of finishing speaking
   - ASR: ~500ms
   - LLM: ~500-1500ms
   - TTS: ~100-500ms
   - Avatar render: ~200ms
   - Network: ~200ms
   - **Total:** 1.5-3 seconds (acceptable)

2. **Avatar Rendering:** Requires GPU for real-time animation
   - Cloud GPU instance (AWS g4dn, etc.)
   - Or pre-rendered animations for common responses

3. **Voice Selection:** Choose voice that matches QA Lead persona
   - Professional, clear, neutral accent
   - Consistent across all interactions

### Acceptance Criteria (Future)

| Criteria | Target |
|----------|--------|
| End-to-end response time | < 3 seconds from user finish speaking |
| Voice naturalness | User rating 4+/5 in feedback |
| Avatar lip sync | Synchronized within 100ms |
| Conversation continuity | Maintains context across exchanges |

---

## Shared Backend Components

### State Store (SQLite)

**Purpose:** Track conversation context, intern progress, and bot state.

**Schema:**

```sql
-- Intern tracking
CREATE TABLE interns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    program TEXT,  -- 'skillbridge', 'vanderbilt', 'other'
    start_date DATE,
    end_date DATE,
    status TEXT,  -- 'onboarding', 'active', 'graduating', 'completed'
    supervisor TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Task assignments
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    intern_id TEXT REFERENCES interns(id),
    github_issue TEXT,  -- e.g., 'pulse#42'
    assigned_at TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT  -- 'assigned', 'in_progress', 'completed', 'blocked'
);

-- Conversation context
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    channel_id TEXT,
    context JSON,  -- Recent messages, current topic
    updated_at TIMESTAMP
);

-- Escalations
CREATE TABLE escalations (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    topic TEXT,
    status TEXT,  -- 'pending', 'acknowledged', 'resolved'
    assigned_to TEXT,
    created_at TIMESTAMP,
    resolved_at TIMESTAMP
);
```

### LLM Brain (Claude Integration)

**Purpose:** Natural language understanding, response generation, judgment calls.

**Usage:**
- Query intent classification (when keywords don't match)
- Response generation for complex queries
- Summarization of meeting transcripts
- Context-aware conversation

**Implementation:**

```python
# src/llm/brain.py
from anthropic import Anthropic

class QABrain:
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)
        self.system_prompt = """You are the AI QA Lead for Cloud Warriors.
        You help with GitHub issue tracking, intern management, and QA processes.
        Be concise, professional, and helpful. When you can't help, escalate to humans."""

    def classify_intent(self, text: str) -> dict:
        """Classify user query intent."""
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            system="Classify the user's intent. Return JSON with 'intent' and 'confidence'.",
            messages=[{"role": "user", "content": text}]
        )
        return parse_json(response.content[0].text)

    def generate_response(self, query: str, context: dict) -> str:
        """Generate response with context."""
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=self.system_prompt,
            messages=[
                {"role": "user", "content": f"Context: {context}\n\nQuery: {query}"}
            ]
        )
        return response.content[0].text
```

### Escalation Manager

**Purpose:** Route to humans when AI can't help or judgment is required.

**Triggers:**
- User explicitly requests human (`escalate`, `talk to human`, `need help`)
- Query confidence < 0.5
- Topic in sensitive list (performance evaluation, termination, conflict)
- Repeated failed queries (user frustrated)

**Implementation:**

```python
# src/bot/escalation.py

SENSITIVE_TOPICS = [
    "performance", "evaluation", "termination", "conflict",
    "complaint", "harassment", "discrimination"
]

class EscalationManager:
    def __init__(self, zoom_notifier, default_contact: str):
        self.zoom = zoom_notifier
        self.default_contact = default_contact

    def should_escalate(self, query: str, confidence: float) -> bool:
        query_lower = query.lower()

        # Explicit request
        if any(word in query_lower for word in ["escalate", "human", "person"]):
            return True

        # Low confidence
        if confidence < 0.5:
            return True

        # Sensitive topic
        if any(topic in query_lower for topic in SENSITIVE_TOPICS):
            return True

        return False

    def escalate(self, user: str, topic: str, context: dict) -> str:
        """Notify human and return acknowledgment."""
        message = f"Escalation from {user}: {topic}\nContext: {context}"
        self.zoom.send(f"{self.default_contact} {message}")

        return f"I've notified {self.default_contact} about your request. They'll follow up shortly."
```

---

## Security Considerations

### Authentication & Authorization

| Component | Auth Method |
|-----------|-------------|
| Zoom webhook | Verification token (header) |
| GitHub API | Personal access token |
| Recall.ai API | API key |
| Claude API | API key |
| n8n | OAuth or API key per integration |

### Data Protection

- **No sensitive data in logs:** Redact tokens, personal info
- **Issue titles only:** Don't expose full issue descriptions (may contain sensitive info)
- **Transcription storage:** Encrypt at rest, auto-delete after 30 days
- **Intern data:** Follow data retention policies

### Rate Limiting

| Service | Limit | Handling |
|---------|-------|----------|
| GitHub API | 5,000/hour | Cache with 60s TTL |
| Zoom webhook | Respond in 3s | Async processing for slow queries |
| Claude API | Varies by tier | Queue and retry |
| User queries | 20/hour per user | In-memory rate limiter |

---

## Implementation Timeline

### Phase 1: Chat Bot (Weeks 1-2)

| Week | Tasks |
|------|-------|
| Week 1 | Set up Flask app, implement query parser, integrate with existing GitHub client |
| Week 1 | Create Zoom Marketplace app, configure webhook |
| Week 2 | Implement all commands (high priority, unassigned, stale, etc.) |
| Week 2 | Add escalation logic, deploy to cloud VM |
| Week 2 | Testing and bug fixes |

### Phase 2: n8n Workflows (Week 3)

| Day | Tasks |
|-----|-------|
| Day 1-2 | Set up n8n instance, configure integrations (Zoom, Google Docs, GitHub) |
| Day 3-4 | Build onboarding workflow |
| Day 5 | Build weekly feedback prep workflow |
| Day 6 | Build offboarding workflow |
| Day 7 | Testing and refinement |

### Phase 3: Meeting Presence (Weeks 4-5)

| Week | Tasks |
|------|-------|
| Week 4 | Sign up for Recall.ai, implement API client |
| Week 4 | Build meeting join flow (user sends link → bot joins) |
| Week 5 | Implement transcription handling, meeting notes |
| Week 5 | Create avatar image, configure bot appearance |
| Week 5 | Testing with real meetings |

### Phase 4: Voice/Avatar (Future)

| Week | Tasks |
|------|-------|
| TBD | Evaluate Cartesia vs AIAvatarKit vs alternatives |
| TBD | Set up GPU infrastructure |
| TBD | Implement speech pipeline |
| TBD | Integrate with Recall.ai audio streaming |

---

## Success Metrics

### Quantitative

| Metric | Target | Measurement |
|--------|--------|-------------|
| Query response accuracy | 95%+ | Automated testing + user feedback |
| Response time | < 3 seconds | Logging |
| Uptime | 99%+ | Health checks |
| User satisfaction | 4+/5 | Periodic survey |
| Escalation rate | < 10% | Logging |
| Onboarding completion | 100% | Workflow tracking |

### Qualitative

- Users prefer bot for routine queries over manual lookup
- Interns receive consistent onboarding experience
- Meeting notes are useful and accurate
- Humans are only involved for judgment calls

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Zoom API changes | Medium | High | Monitor changelog, abstract API calls |
| Recall.ai service disruption | Low | High | Fallback to chat-only mode |
| LLM hallucination | Medium | Medium | Keyword matching first, confidence thresholds |
| User confusion about capabilities | High | Low | Clear help command, explicit escalation |
| Cost overrun (API usage) | Low | Medium | Usage monitoring, alerts at thresholds |

---

## Resources Required

### Services

| Service | Purpose | Est. Monthly Cost |
|---------|---------|-------------------|
| Cloud VM (e.g., DigitalOcean) | Host chat bot | $10-20 |
| n8n Cloud (or self-hosted) | Workflow automation | $0-20 |
| Recall.ai | Meeting presence | $30-60 |
| Anthropic API | LLM brain | $20-50 |
| **Total** | | **$60-150** |

### Development

| Resource | Effort |
|----------|--------|
| Backend development | 3-4 weeks |
| Zoom app configuration | 1-2 days |
| n8n workflow design | 3-5 days |
| Testing and QA | Ongoing |
| Documentation | Ongoing |

---

## Appendix A: Environment Variables

```bash
# GitHub
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
GITHUB_ORG=cloudwarriors-ai

# Zoom
ZOOM_BOT_VERIFICATION_TOKEN=xxxxxxxx
ZOOM_WEBHOOK_URL=https://hooks.zoom.us/xxxxxxxx
ZOOM_BOT_JID=xxxxxxxx@xmpp.zoom.us

# Anthropic (Claude)
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx

# Recall.ai
RECALL_API_KEY=xxxxxxxx

# n8n
N8N_WEBHOOK_URL=https://your-n8n.com/webhook/xxxxx

# Application
ESCALATION_CONTACT=@chad3
LOG_LEVEL=INFO
DATABASE_PATH=data/state.db
```

---

## Appendix B: API Endpoints

### Chat Bot

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/zoom/webhook` | POST | Receive Zoom messages |
| `/api/query` | POST | Direct API query (for n8n) |
| `/api/intern/{id}` | GET | Get intern status |
| `/api/escalate` | POST | Create escalation |

### Meeting Bot

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/meeting/join` | POST | Request bot join meeting |
| `/meeting/{id}/status` | GET | Get meeting bot status |
| `/meeting/{id}/transcript` | GET | Get meeting transcript |
| `/transcription` | POST | Receive real-time transcription (webhook) |

---

## Appendix C: Council Session Reference

This plan was developed through a Multi-Turn Council session with three expert personas:

- **Alex Chen (Senior AI Developer):** Advocated for phased approach, third-party services over custom SDK, testable keyword parsing
- **Sam Rivera (Zoom Expert):** Confirmed Zoom API constraints, recommended Recall.ai for meeting bots, designed escalation UX
- **Jordan Taylor (QA Expert):** Analyzed QA Lead responsibilities, defined acceptance criteria, ensured human-in-the-loop for judgment calls

Full council protocol: `docs/COUNCIL_PROTOCOL.md`
Persona definitions: `docs/PERSONAS.md`
