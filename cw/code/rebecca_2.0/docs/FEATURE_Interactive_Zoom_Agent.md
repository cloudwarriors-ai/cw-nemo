# Feature Plan: Interactive Zoom Agent

**Status**: Planned Enhancement
**Priority**: Future (implement when team requests real-time Q&A)
**Effort Estimate**: 1-2 days
**Dependencies**: Phase A (MVP) complete, Phase B (Hardening) recommended first

---

## Overview

Transform the QA Continuity Agent from a scheduled report generator into an interactive bot that responds to questions in Zoom chat channels.

### Current State
- Scheduled reports run weekly via Task Scheduler
- One-way push: script generates report → posts to Zoom
- No interaction capability

### Proposed State
- Always-on bot listens in Zoom channel
- Users ask questions like "@qabot high priority issues"
- Bot responds with filtered issue data in real-time

---

## How It Works

```
User types in Zoom: "@qabot high priority issues"
    ↓
Zoom sends webhook POST to your endpoint
    ↓
Bot: parses query → fetches from GitHub (cached) → formats response
    ↓
Bot responds in Zoom channel with results
```

---

## Architecture

### New Files
```
qa_continuity_app/
├── src/
│   ├── bot.py               # Flask webhook handler
│   ├── query_parser.py      # Keyword-based query parser
│   ├── cache.py             # Issue caching (60-second TTL)
│   ├── github_client.py     # (existing - reuse)
│   ├── report_generator.py  # (existing - add quick_list format)
│   └── zoom_notifier.py     # (existing - reuse)
├── requirements.txt         # Add: flask, gunicorn
└── .env                     # Add: ZOOM_BOT_VERIFICATION_TOKEN
```

### Dependencies to Add
```
flask>=3.0.0
gunicorn>=21.0.0  # Production server
```

---

## Query Parser Design

**Approach**: Keyword matching (NO LLM)

The adversarial council recommended against using LLM because:
- Data is structured (repo, assignee, priority, labels)
- Queries are predictable
- Keyword matching handles 90%+ of use cases
- LLM adds cost ($11-150/mo), latency, and security risks

### Implementation

```python
# query_parser.py
def parse_query(text: str) -> dict:
    """Parse user query into structured filter."""
    text = text.lower()

    query = {
        "filter": None,
        "repo": None,
        "assignee": None
    }

    # Filter detection
    if "high" in text and "priority" in text:
        query["filter"] = "high_priority"
    elif "unassigned" in text:
        query["filter"] = "unassigned"
    elif "stale" in text:
        query["filter"] = "stale"
    elif "hygiene" in text:
        query["filter"] = "hygiene"
    elif "summary" in text or "all" in text:
        query["filter"] = "summary"

    # Repo detection: "repo:pulse" or "in pulse"
    if "repo:" in text:
        parts = text.split("repo:")[1].split()
        if parts:
            query["repo"] = parts[0]

    # Assignee detection: "assigned to john"
    if "assigned to " in text:
        parts = text.split("assigned to ")[1].split()
        if parts:
            query["assignee"] = parts[0]

    return query
```

---

## Supported Commands

| User Says | Bot Response |
|-----------|--------------|
| `high priority` | Issues with priority:high label |
| `unassigned` | Issues without assignee |
| `stale` | Issues with no update in 14+ days |
| `hygiene` | Issues missing required fields |
| `repo:pulse` | All issues in specific repo |
| `assigned to john` | Issues assigned to specific person |
| `summary` or `all` | Count breakdown by repo |
| `help` | List of available commands |

### Example Responses

**"high priority"**
```
## High Priority Issues (3)

- 🔥 [pulse#42](url) Fix auth timeout (alice)
- 🔥 [macd#15](url) Database migration (bob)
- 🔥 [pulse#38](url) API rate limiting (UNASSIGNED)
```

**"summary"**
```
## Issue Summary

| Repo | Open | High | Unassigned | Stale |
|------|------|------|------------|-------|
| pulse | 12 | 2 | 3 | 1 |
| macd | 8 | 1 | 0 | 2 |
| **Total** | **20** | **3** | **3** | **3** |
```

---

## Bot Endpoint

```python
# bot.py
import os
import time
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from .github_client import GitHubClient
from .query_parser import parse_query
from .report_generator import ReportGenerator

load_dotenv()

app = Flask(__name__)

ZOOM_BOT_TOKEN = os.getenv("ZOOM_BOT_VERIFICATION_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_ORG = os.getenv("GITHUB_ORG", "cloudwarriors-ai")
REPOS = ["repo1", "repo2"]  # Configure your repos

# Initialize clients
github_client = GitHubClient(token=GITHUB_TOKEN, org=GITHUB_ORG)
report_generator = ReportGenerator()

# Cache (refresh every 60 seconds)
_cache = {"issues": [], "updated": 0}
CACHE_TTL = 60

def get_cached_issues():
    """Fetch issues with caching to avoid GitHub rate limits."""
    global _cache
    if time.time() - _cache["updated"] > CACHE_TTL:
        _cache["issues"] = github_client.fetch_issues(REPOS)
        _cache["updated"] = time.time()
    return _cache["issues"]

def filter_issues(issues, query):
    """Apply query filters to issue list."""
    result = issues

    if query["repo"]:
        result = [i for i in result if i.repo.lower() == query["repo"].lower()]

    if query["assignee"]:
        result = [i for i in result if i.assignee and
                  i.assignee.lower() == query["assignee"].lower()]

    if query["filter"] == "high_priority":
        result = [i for i in result if i.priority and i.priority.lower() == "high"]
    elif query["filter"] == "unassigned":
        result = [i for i in result if not i.assignee]
    elif query["filter"] == "stale":
        result = [i for i in result if i.is_stale]
    elif query["filter"] == "hygiene":
        result = [i for i in result if not i.assignee or not i.priority]

    return result

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})

@app.route("/zoom/webhook", methods=["POST"])
def handle_zoom():
    """Handle incoming Zoom webhook."""
    data = request.json

    # Verify request is from Zoom
    token = data.get("token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != ZOOM_BOT_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    # Extract message text
    payload = data.get("payload", {})
    text = payload.get("text", "").strip()
    user = payload.get("userName", "unknown")

    # Handle help command
    if not text or text.lower() == "help":
        response = get_help_text()
    else:
        # Parse and execute query
        query = parse_query(text)
        issues = get_cached_issues()

        if query["filter"] == "summary":
            response = report_generator.generate_summary(issues)
        else:
            filtered = filter_issues(issues, query)
            response = report_generator.format_quick_list(filtered, query)

    # Log query (redacted)
    print(f"[QUERY] user={user[:3]}*** filter={query.get('filter')} results={len(filtered) if 'filtered' in dir() else 'N/A'}")

    return jsonify({"text": response})

def get_help_text():
    return """## QA Bot Commands

**Filters:**
- `high priority` - Show high priority issues
- `unassigned` - Show unassigned issues
- `stale` - Show issues with no update in 14+ days
- `hygiene` - Show issues missing required fields
- `summary` - Show count breakdown by repo

**Scoping:**
- `repo:name` - Filter to specific repo
- `assigned to name` - Filter to specific person

**Examples:**
- `high priority`
- `unassigned repo:pulse`
- `assigned to alice`
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
```

---

## Deployment Options

| Option | Setup Time | Monthly Cost | Best For |
|--------|------------|--------------|----------|
| **Local + ngrok** | 1 hour | Free | Development/testing |
| **Docker + VM** | 2-3 hours | ~$5/mo | Simple production |
| **AWS Lambda** | 4-6 hours | ~$1-5/mo | Scalable, serverless |

### Local Development

```bash
# Terminal 1: Start bot
cd qa_continuity_app
pip install flask
python -m src.bot

# Terminal 2: Expose via ngrok
ngrok http 5000
# Copy https://xxx.ngrok.io/zoom/webhook to Zoom bot config
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ ./src/
COPY .env .
CMD ["gunicorn", "-b", "0.0.0.0:5000", "src.bot:app"]
```

```bash
docker build -t qa-bot .
docker run -d -p 5000:5000 --env-file .env qa-bot
```

---

## Security Requirements

Based on adversarial council (Security Engineer) review:

### Must Have
- [ ] Verify Zoom webhook token on every request
- [ ] Rate limit: 20 queries per user per hour
- [ ] Query whitelist: only allow defined commands
- [ ] No issue descriptions in responses (titles only)
- [ ] 30-second timeout on all external API calls
- [ ] Structured logging (no sensitive data)

### Implementation

```python
# Rate limiting (simple in-memory)
from collections import defaultdict
import time

_rate_limits = defaultdict(list)
RATE_LIMIT = 20  # requests per hour

def check_rate_limit(user_id: str) -> bool:
    now = time.time()
    hour_ago = now - 3600

    # Clean old entries
    _rate_limits[user_id] = [t for t in _rate_limits[user_id] if t > hour_ago]

    if len(_rate_limits[user_id]) >= RATE_LIMIT:
        return False

    _rate_limits[user_id].append(now)
    return True
```

---

## Caching Strategy

To avoid hitting GitHub API rate limits (5,000/hour):

```python
import time
from threading import Lock

class IssueCache:
    def __init__(self, ttl_seconds=60):
        self.ttl = ttl_seconds
        self.issues = []
        self.updated = 0
        self.lock = Lock()

    def get(self, github_client, repos):
        with self.lock:
            if time.time() - self.updated > self.ttl:
                self.issues = github_client.fetch_issues(repos)
                self.updated = time.time()
            return self.issues

    def invalidate(self):
        with self.lock:
            self.updated = 0
```

---

## Zoom Bot Setup

### 1. Create Zoom App
1. Go to [Zoom Marketplace](https://marketplace.zoom.us/)
2. Develop → Build App → Chatbot
3. Configure OAuth scopes: `chat_channel:write`, `chat_message:read`

### 2. Configure Webhook
1. In app settings → Event Subscriptions
2. Add endpoint: `https://your-domain.com/zoom/webhook`
3. Subscribe to: `chat_message.received`

### 3. Get Verification Token
1. In app settings → Features → Chatbot
2. Copy "Verification Token"
3. Add to `.env`: `ZOOM_BOT_VERIFICATION_TOKEN=xxxxx`

---

## Testing Checklist

- [ ] Bot responds to "help" command
- [ ] "high priority" returns only high priority issues
- [ ] "unassigned" returns only unassigned issues
- [ ] "stale" returns only stale issues
- [ ] "repo:X" filters to specific repo
- [ ] "assigned to X" filters to specific person
- [ ] Invalid commands return help text
- [ ] Rate limiting blocks after 20 requests/hour
- [ ] Unauthorized requests return 401
- [ ] Health endpoint returns 200

---

## Future Enhancements

If keyword matching proves insufficient, consider:

### Natural Language Processing (Phase D)
- Add LLM layer for query interpretation
- Estimated cost: $11-150/month in API fees
- Security risk: Prompt injection - requires careful sanitization
- See adversarial council notes in main plan

### Slash Commands
- `/qabot priority high` - Structured command syntax
- Easier to parse than natural language
- No LLM required

---

## Adversarial Council Notes

This feature was reviewed by three AI developer personas:

| Persona | Key Feedback |
|---------|--------------|
| **Marcus (Security)** | No LLM - prompt injection risk. Add rate limiting, token verification. |
| **Dana (Pragmatist)** | Keyword matching is sufficient. ~300 lines of new code. Ship in 1-2 days. |
| **Jordan (DevOps)** | Need always-on service. Lambda or Docker. Add health checks, logging. |

Full council analysis available in main implementation plan.
