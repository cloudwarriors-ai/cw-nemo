# Meeting & Voice Integration Architecture

Comprehensive index of how the QA bot joins meetings, processes transcriptions, and delivers voice responses.

---

## Executive Summary

This document indexes all code related to how the QA bot joins Zoom meetings, processes transcriptions in real-time, generates responses, and delivers them via voice and avatar output. The system follows a complete data pipeline from meeting join → transcription → LLM processing → voice synthesis → delivery to meeting participants.

---

## 1. Meeting Join Flow (Recall.ai Integration)

### Entry Point: `POST /api/meeting/join`
**File:** `src/bot/routes/meetings.py` (lines 43-141)

**Request Body:**
```json
{
  "meeting_url": "https://zoom.us/meeting/...",
  "bot_name": "QA Bot (optional)",
  "user_id": "requesting_user (optional)",
  "enable_voice": true
}
```

**Key Steps:**
1. Validates meeting URL domain (Zoom, Teams, Google Meet)
2. Rate limit check (default 5 meetings/hour per user)
3. Generates pre-meeting_id for Output Media URL mapping
4. Calls `MeetingHandler.join_meeting()`

### Core Component: `RecallClient`
**File:** `src/meeting/recall_client.py` (lines 28-415)

**Class: RecallClient**
- **Base URL:** `https://us-west-2.recall.ai/api/v1`
- **Authentication:** Token-based via `Authorization: Token {api_key}` header
- **Timeout:** 30 seconds (configurable)
- **Retries:** 3 attempts with exponential backoff (0.5s * 2^attempt)

**Critical Methods:**

| Method | Purpose | Parameters |
|--------|---------|-----------|
| `create_bot()` | Create and join bot to meeting | meeting_url, bot_name, bot_image_url, transcription_provider, automatic_leave, recording_mode, output_media_url, variant |
| `get_bot_status()` | Poll current bot status | bot_id |
| `wait_for_status()` | Wait for bot to reach status | bot_id, target_status, timeout_seconds, poll_interval |
| `leave_meeting()` | Make bot leave meeting | bot_id |
| `delete_bot()` | Clean up bot and data | bot_id |
| `get_transcript()` | Fetch final transcript | bot_id |
| `send_chat_message()` | Send chat in meeting | bot_id, message |

**Bot Status Lifecycle:**
```
ready → joining → in_waiting_room → in_call → recording → done
                                                           ↓
                                                    error/fatal
```

**Output Media Configuration:**
- For avatar/voice output, `output_media_url` is set to: `{PUBLIC_URL}/avatar/page?meeting_id={meeting_id}`
- Recall.ai renders this webpage as the bot's camera
- Variant set to `web` for Output Media support

### Core Component: `MeetingHandler`
**File:** `src/meeting/meeting_handler.py` (lines 17-986)

**Class: MeetingHandler**
- Manages meeting lifecycle from join → completion
- Integrates with SQLite database for persistence
- Optionally wires voice pipeline for voice responses

**Key Responsibilities:**

| Method | Purpose |
|--------|---------|
| `join_meeting()` | Request bot to join meeting, store record |
| `get_meeting_status()` | Get current status with live Recall.ai poll |
| `leave_meeting()` | Make bot leave, mark status |
| `get_transcript()` | Get cached or fetch transcript |
| `get_meeting_notes()` | Generate formatted notes from transcript |
| `list_meetings()` | List with optional status/requester filters |
| `handle_transcription()` | Process incoming transcription webhook |
| `handle_status_update()` | Process Recall.ai bot status changes |

---

## 2. Database Schema (Persistent Storage)

**File:** `src/bot/database.py` (lines 434-515)

### meetings table
```sql
CREATE TABLE meetings (
    id TEXT PRIMARY KEY,                    -- Internal meeting ID
    bot_id TEXT NOT NULL,                   -- Recall.ai bot ID
    meeting_url TEXT NOT NULL,              -- Original meeting URL
    requested_by TEXT,                      -- User who requested join
    channel_id TEXT,                        -- Zoom channel for updates
    status TEXT DEFAULT 'joining',          -- Current state
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    ended_at TIMESTAMP
);
-- Indexes: idx_meetings_status, idx_meetings_bot
```

**Status Values:**
- `joining` - Bot is trying to join
- `waiting` - In waiting room
- `in_call` - In meeting, not recording
- `recording` - Capturing/processing
- `completed` - Meeting ended
- `left` - Bot left manually
- `abandoned` - Stale (30+ min in joining/waiting)
- `error` - Failed to join

### transcripts table
```sql
CREATE TABLE transcripts (
    meeting_id TEXT PRIMARY KEY REFERENCES meetings(id),
    segments TEXT,                          -- JSON array of segments
    fetched_at TIMESTAMP
);
```

### transcript_segments table
```sql
CREATE TABLE transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT REFERENCES meetings(id),
    speaker TEXT,                           -- Speaker name
    text TEXT,                              -- Transcribed text
    start_time REAL,                        -- Segment start (seconds)
    end_time REAL,                          -- Segment end (seconds)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Index: idx_transcript_segments_meeting(meeting_id, start_time)
```

---

## 3. Transcription Processing

### Real-Time Transcription Webhook
**File:** `src/bot/routes/meetings.py` (lines 230-273)

**Endpoint:** `POST /meeting/transcription`
- Receives from Recall.ai in real-time
- Calls `MeetingHandler.handle_transcription(data)`

### TranscriptionProcessor
**File:** `src/meeting/transcription.py` (lines 13-395)

**Purpose:** Process and alert on transcription events

**Key Methods:**
| Method | Purpose |
|--------|---------|
| `process_webhook()` | Parse incoming webhook, check keywords, store |
| `process_partial()` | Handle non-final transcripts (for real-time display) |
| `get_live_transcript()` | Get segments since timestamp |
| `get_full_transcript()` | Get complete meeting transcript |
| `format_transcript()` | Format as readable text with speaker labels |
| `get_speakers()` | Get unique speakers in meeting |
| `search_transcript()` | Full-text search with speaker filter |

**Alert Keywords (Default):**
```
action item, todo, follow up, deadline, urgent, blocker, qa bot
```

### Recall.ai Webhook Payload Parsing
**File:** `src/meeting/meeting_handler.py` (lines 590-720)

**Handles Multiple Webhook Formats:**

Format 1 (Realtime Deepgram):
```json
{
  "transcript": {
    "words": [{"text": "hello", "start_timestamp": {}, "end_timestamp": {}}],
    "participant": {"name": "John"}
  }
}
```

Format 2 (Nested Data):
```json
{
  "data": {
    "transcript": {
      "words": [...],
      "participant": {...}
    }
  }
}
```

Format 3 (Fallback):
```json
{
  "data": {
    "data": {
      "words": [...],
      "speaker": "John"
    }
  }
}
```

**Extraction Logic:**
1. Tries 5 possible locations for bot_id (direct, nested in data, recording)
2. Tries 5 possible locations for transcript words/text
3. Falls back to most recent active meeting if bot_id not found
4. Extracts speaker name, text, start_time, end_time from words array

---

## 4. Voice Response Triggering

### Wake Word Detection
**File:** `src/meeting/meeting_handler.py` (lines 757-877)

**Wake Word Variants (Checked First):**
```python
['qa bot', 'qabot', 'q a bot', 'q.a. bot',
 'qa about',  # Common misrecognition
 'qava', 'queba', 'qaba',
 'cue a bot', 'queue a bot', 'qa bought',
 'qa bott', 'qa butt', 'qa but',
 'hey qa bot', 'hey qabot',
 'q about', 'cube a bot', 'q a bought']
```

**Fuzzy Matching (If No Exact Match):**
1. **Soundex Matching:** Phonetic encoding for misrecognitions like "queba" → "qa bot"
   - Soundex codes map 4-letter representations
   - Examples: Q (Q-Bot) vs Q-V-A (Queba) → similar phonetic patterns

2. **Levenshtein Distance:** Edit distance matching (≤2 edits allowed)
   - "qaba" vs "qabot" = 1 edit distance → match
   - "kuba" vs "qabot" = 2 edit distances → match

**Voice Response Trigger:**
```python
def _should_respond_voice(text: str, speaker: str) -> Tuple[bool, str]:
    # Layer 1: Check exact variants
    # Layer 2: Fuzzy phonetic matching on first 1-2 words
    # Extract query after wake word
    # Return (should_respond, extracted_query)
```

**Debounce Mechanism:**
- Default: 3 seconds between voice responses per meeting
- Prevents rapid-fire duplicate responses
- Thread-safe with lock protection

### Voice Response Workflow
**File:** `src/meeting/meeting_handler.py` (lines 957-986)

```
_trigger_voice_response()
    ↓
Run in background thread (non-blocking webhook)
    ↓
voice_pipeline.respond_to_query(query, bot_id)
```

---

## 5. Voice Pipeline (ASR → LLM → TTS → Output)

### Architecture
**File:** `src/voice/voice_pipeline.py` (lines 249-1083)

```
Audio Input (Recall.ai webhook)
    ↓
VAD (Voice Activity Detection) - Silero ML or Energy-based
    ↓
Buffer Speech Until Silence Detected
    ↓
ASR (Speech-to-Text) - OpenAI Whisper
    ↓
Semantic Cache Check (can reduce latency by 86%)
    ↓
LLM Processing (if cache miss)
    ↓
TTS (Text-to-Speech) - Cartesia or OpenAI
    ↓
Output to Meeting (WebSocket or Recall.ai API)
```

### Core Class: `VoicePipeline`

**Initialization:**
```python
VoicePipeline(
    speech_processor: SpeechProcessor,      # ASR
    tts_client: TTSClient,                  # TTS
    query_handler: Callable[[str], str],    # LLM
    recall_bot_id: str = None,
    recall_api_key: str = None,
    use_silero_vad: bool = True,            # 95%+ accuracy ML-based
    enable_cache: bool = True,              # Semantic response cache
    enable_barge_in: bool = True,           # Interrupt detection
    logger: logging.Logger = None
)
```

**Key Methods:**

| Method | Purpose |
|--------|---------|
| `start()` | Start background worker thread |
| `stop()` | Stop worker and cleanup |
| `process_audio_chunk()` | Process incoming audio frame with VAD + barge-in detection |
| `respond_to_query()` | Process text query and send voice response (main entry point) |
| `process_text_query()` | Test endpoint: text → audio |
| `get_latency_stats()` | Get performance metrics |
| `get_pipeline_stats()` | Comprehensive stats |

**State Management:**
- `is_processing` - Currently processing audio
- `is_speaking` - Bot outputting audio
- `_barge_in_triggered` - User interrupted bot
- `audio_buffer` - Thread-safe bytearray for speech
- `interaction_history` - Last 1000 interactions (FIFO eviction)

### 5.1 Voice Activity Detection (VAD)

**File:** `src/voice/speech_processor.py` (lines 166-443)

**SileroVAD (Recommended):**
- Model: Silero VAD from PyTorch Hub
- Format: ONNX for fast CPU inference
- Accuracy: 95%+ in noisy environments
- Latency: <1ms per 30ms audio chunk
- Threshold: 0.5 (speech probability)
- Min speech duration: 250ms
- Min silence duration: 500ms

**Fallback to Energy-Based VAD:**
- If PyTorch not available
- RMS energy calculation on 16-bit PCM
- Energy threshold: 0.01

**Configuration:**
```python
create_vad(use_silero=True, **kwargs) -> VAD
```

### 5.2 Speech-to-Text (ASR)

**File:** `src/voice/speech_processor.py` (lines 28-164)

**Class: SpeechProcessor**

```python
SpeechProcessor(
    api_key: str,                           # OpenAI API key
    model: str = "whisper-1",
    language: str = "en",
    prompt: str = "QA Bot, GitHub, issues, interns, Cloud Warriors",
    logger: logging.Logger = None
)
```

**Transcription Result:**
```python
@dataclass
class TranscriptionResult:
    text: str                               # Transcribed text
    confidence: float                       # 1.0 (Whisper always returns 1.0)
    language: str                           # Detected language
    duration_seconds: float                 # Audio duration
    processing_time_ms: float               # API latency
```

**Implementation:**
- Uses OpenAI Whisper API v1
- Input: Raw audio bytes (webm, wav, mp3)
- Output: Verbose JSON with text and metadata
- Timeout: 30 seconds
- Prompt guides recognition toward domain-specific terms

### 5.3 Semantic Cache

**File:** `src/voice/voice_pipeline.py` (lines 58-247)

**Purpose:** Cache LLM responses based on query similarity to reduce latency by 86%

**Cache Entry:**
```python
@dataclass
class CacheEntry:
    query: str
    response: str
    audio_data: bytes                       # Limited to 100KB
    created_at: float
    hit_count: int = 0
```

**Configuration:**
- Similarity threshold: 0.85 (Jaccard token-based)
- Max entries: 500
- TTL: 3600 seconds (1 hour)
- Search scope: Most recent 100 entries (O(1) performance)

**Similarity Algorithm:**
```
Jaccard Similarity = |intersection| / |union| of tokens
```

**Example:**
- Query 1: "What is the status of the CI pipeline?"
- Query 2: "Can you tell me about the CI build?"
- Similarity: 0.6 (6 shared tokens / 10 total)
- Below threshold 0.85 → cache miss → LLM processes

**LRU Eviction:**
- When full (500 entries), evict 10% (50 entries)
- Evict by: hit count (ascending), then age (ascending)
- Keeps frequently-used responses

**Stats Available:**
```python
cache.get_stats() → {
    "entries": 45,
    "hits": 120,
    "misses": 30,
    "hit_rate": 0.8,
    "max_entries": 500,
    "ttl_seconds": 3600
}
```

### 5.4 Text-to-Speech (TTS)

**File:** `src/voice/tts_client.py` (lines 46-358)

**Class: CartesiaTTS (Primary)**
```python
CartesiaTTS(
    api_key: str,
    voice_id: str = None,                   # Defaults to professional_female
    model_id: str = "sonic-english",
    sample_rate: int = 24000,
    output_format: str = "mp3",
    logger: logging.Logger = None
)
```

**Performance:**
- Time to first audio: 40ms
- Sample rate: 24kHz
- Output formats: mp3, pcm_s16le, wav

**Predefined Voices:**
```python
{
    "professional_male": "a0e99841-438c-4a64-b679-ae501e7d6091",
    "professional_female": "248be419-c632-4f23-adf1-5324ed7dbf1d",
    "friendly_male": "63ff761f-c1e8-414b-b969-d1833d1c870c",
    "friendly_female": "71a7ad14-091c-4e8e-a314-022ece01c121"
}
```

**Streaming Support:**
- WebSocket at `wss://api.cartesia.ai/tts/websocket`
- Enables playback to start before synthesis complete
- Status messages: transcript request, audio chunks, done

**Class: OpenAITTS (Fallback)**
- Model: tts-1 or tts-1-hd
- Voices: alloy, echo, fable, onyx, nova, shimmer
- Output: MP3 (24kHz)
- No streaming support (full synthesis first)

**Response Sanitization for Voice:**
- Removes markdown (bold, italic, headers, code blocks)
- Converts URLs to "link"
- Removes bullets/numbers
- Truncates to 400 characters at sentence boundary
- Max length prevents Cartesia timeout

---

## 6. Response Delivery to Meeting

### Primary Path: WebSocket (Output Media)
**File:** `src/voice/voice_pipeline.py` (lines 559-593)

```python
def _send_audio_via_websocket(
    audio_data: bytes,
    audio_format: str
) -> bool:
    manager = get_avatar_ws_manager(self.logger)
    if manager.is_connected(self.recall_bot_id):
        return manager.send_audio(self.recall_bot_id, audio_data, audio_format)
    return False
```

**Connection Management:**
- File: `src/avatar/websocket_manager.py`
- Maintains active WebSocket connections per bot_id
- Maps meeting_id → bot_id for URL routing
- ID mapping stored: `add_id_mapping(meeting_id, bot_id)`

**Avatar Webpage (Output Media):**
- URL: `{PUBLIC_URL}/avatar/page?meeting_id={meeting_id}`
- Rendered by Recall.ai as bot's camera feed
- Receives audio via WebSocket for playback
- Can show avatar state: listening, thinking, speaking, error

### Fallback Path: Recall.ai API
**File:** `src/voice/voice_pipeline.py` (lines 594-625)

```python
POST https://us-west-2.recall.ai/api/v1/bot/{bot_id}/output_audio
Headers:
    Authorization: Token {api_key}
    Content-Type: application/json

Body: {
    "kind": "mp3",
    "b64_data": "<base64 encoded audio>"
}
```

**Conversion:**
- PCM to MP3 via pydub/ffmpeg if needed (lines 626-664)
- Returns fallback if pydub unavailable

### Streaming Response Flow
**File:** `src/voice/voice_pipeline.py` (lines 832-867)

```
respond_to_query(query, bot_id, use_streaming=True)
    ↓
Send "thinking" state to avatar
    ↓
Process query through LLM
    ↓
Sanitize response text for voice
    ↓
Send "speaking" state to avatar
    ↓
Stream audio chunks from TTS:
    for chunk in tts_client.synthesize_stream(text):
        _send_audio_to_meeting(chunk)
    ↓
Send "listening" state (flush buffer, trigger playback)
```

**Barge-In Detection:**
```python
if user_speaks_while_bot_speaking:
    send state "barge_in" to avatar
    mark is_speaking = False
    stop audio playback
```

---

## 7. Webhook Endpoints

### Meeting Endpoints
**File:** `src/bot/routes/meetings.py`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/meeting/join` | POST | Request bot to join meeting |
| `/api/meeting/<id>` | GET | Get meeting status/details |
| `/api/meeting/<id>/leave` | POST | Make bot leave |
| `/api/meeting/<id>/transcript` | GET | Get meeting transcript |
| `/api/meeting/<id>/notes` | GET | Get AI-generated notes |
| `/api/meeting/<id>/search` | GET | Search transcript (q param) |
| `/api/meeting/<id>/speakers` | GET | Get unique speakers |
| `/api/meetings` | GET | List meetings (status, limit filters) |
| `/api/meetings/cleanup` | POST | Clean stale/old records |
| `/meeting/transcription` | POST | **Recall.ai real-time transcription webhook** |
| `/meeting/status` | POST | **Recall.ai bot status update webhook** |

### Voice Endpoints
**File:** `src/bot/routes/voice.py`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/voice/status` | GET | Get voice pipeline status + stats |
| `/api/voice/tts` | POST | Generate speech from text (TTS only) |
| `/api/voice/query` | POST | Text query → audio response |
| `/api/voice/start/<meeting_id>` | POST | Start voice for active meeting |
| `/api/voice/stop` | POST | Stop voice pipeline |
| `/voice/audio` | POST | **Recall.ai real-time audio webhook** |

---

## 8. Environment Variables & Configuration

### Required Variables
**File:** `.env.example`

**Recall.ai (Phase 3):**
```
RECALL_API_KEY=<API key from recall.ai dashboard>
RECALL_BOT_NAME=QA Bot (display name in meetings)
RECALL_BOT_IMAGE=https://... (bot avatar image)
RECALL_TRANSCRIPTION_SECRET=<webhook auth secret>
MEETING_RATE_LIMIT=5 (meetings/hour)
```

**Voice (Phase 4):**
```
VOICE_ENABLED=true (or false)
OPENAI_API_KEY=sk-... (for Whisper ASR)
CARTESIA_API_KEY=... (low-latency TTS, optional)
```

**Application:**
```
PUBLIC_URL=https://example.com (for webhooks and Output Media)
DB_PATH=data/state.db (SQLite database)
RECALL_TRANSCRIPTION_SECRET=... (webhook HMAC secret)
```

**LLM Processing:**
```
OPENROUTER_API_KEY=sk-or-... (for voice query handling)
MODEL=anthropic/claude-haiku-4.5
```

### Configuration Classes
**File:** `src/bot/config.py`

```python
@dataclass
class MeetingConfig:
    cleanup_stale_minutes: int = 30  # Abandon joining/waiting meetings
    cleanup_old_days: int = 30       # Delete completed meetings

@dataclass
class LLMConfig:
    timeout_seconds: int = 5
    max_retries: int = 2
    max_tokens: int = 500
    temperature: float = 0.3
```

---

## 9. Complete Data Flow Example

### Scenario: User asks "QA bot, what's the status of issue #42?"

```
1. TRANSCRIPTION WEBHOOK
   Recall.ai → POST /meeting/transcription
   Payload: {
     "data": {
       "transcript": {
         "words": [
           {"text": "qa", "start_timestamp": {...}},
           {"text": "bot", ...},
           {"text": "what's", ...},
           ...
         ],
         "participant": {"name": "John"}
       }
     }
   }

2. TRANSCRIPTION PROCESSING
   MeetingHandler.handle_transcription(data)
   ├─ Extract from nested structure
   ├─ Get speaker: "John"
   ├─ Get text: "qa bot what's the status of issue 42"
   └─ Store in transcript_segments table

3. WAKE WORD DETECTION
   _should_respond_voice("qa bot what's the status of issue 42", "John")
   ├─ Layer 1: Check variants → found "qa bot"
   ├─ Extract query: "what's the status of issue 42"
   ├─ Check debounce (3s): PASS
   └─ Return (True, "what's the status of issue 42")

4. TRIGGER VOICE RESPONSE (background thread)
   _trigger_voice_response("what's the status of issue 42", bot_id, meeting_id)

5. VOICE PIPELINE: respond_to_query()

   5a. AVATAR STATE: Send "thinking" via WebSocket
       manager.send_state(bot_id, "thinking", "Processing...")

   5b. LLM PROCESSING:
       query_handler("what's the status of issue 42")
       ├─ Query: _process_query() → QABrain.query()
       ├─ GitHub API: Get issue #42 details
       └─ Response: "Issue #42 is currently open. Last updated..."

   5c. TEXT SANITIZATION:
       Remove markdown, URLs, truncate to 400 chars
       Output: "Issue 42 is currently open. Last updated yesterday."

   5d. AVATAR STATE: Send "speaking"
       manager.send_state(bot_id, "speaking", "Speaking...")

   5e. TTS (Text-to-Speech):
       CartesiaTTS.synthesize_stream("Issue 42 is currently open...")
       └─ Yields: [chunk1_bytes, chunk2_bytes, ...]
       └─ Cartesia WebSocket: 40ms to first audio

   5f. SEND AUDIO TO MEETING (streaming):
       For each chunk:
           manager.send_audio(bot_id, chunk, "mp3")
       OR fallback:
           POST /bot/{bot_id}/output_audio with base64 audio

   5g. CACHE RESPONSE:
       SemanticCache.put(
           query="what's the status of issue 42",
           response="Issue 42 is currently open...",
           audio_data=<bytes>  # Limited to 100KB
       )

   5h. AVATAR STATE: Send "listening" (playback trigger)
       manager.send_state(bot_id, "listening", "Response complete")

6. MEETING PARTICIPANTS HEAR
   Cartesia TTS audio plays in meeting via Recall.ai bot speaker
   Avatar shows "speaking" state while audio plays
   Audio plays at natural speed (24kHz MP3)

7. INTERACTION HISTORY
   Store in voice_pipeline.interaction_history:
   {
       "id": "voice-1705264800123",
       "user_speech": "qa bot what's the status of issue 42",
       "response_text": "Issue 42 is currently open...",
       "audio_duration_ms": 2500,
       "total_latency_ms": 1200,
       "timestamp": 1705264800.123
   }
```

---

## 10. Key Classes & Responsibilities

| Class | File | Purpose |
|-------|------|---------|
| `RecallClient` | `src/meeting/recall_client.py` | Direct API client for Recall.ai service |
| `MeetingHandler` | `src/meeting/meeting_handler.py` | Orchestrate meeting lifecycle |
| `TranscriptionProcessor` | `src/meeting/transcription.py` | Process and store transcripts |
| `VoicePipeline` | `src/voice/voice_pipeline.py` | End-to-end voice interaction |
| `SpeechProcessor` | `src/voice/speech_processor.py` | Speech recognition and VAD |
| `CartesiaTTS` | `src/voice/tts_client.py` | Low-latency text-to-speech |
| `OpenAITTS` | `src/voice/tts_client.py` | Fallback text-to-speech |
| `SemanticCache` | `src/voice/voice_pipeline.py` | LLM response caching |

---

## 11. Performance Characteristics

### Latency (End-to-End)
| Component | Latency |
|-----------|---------|
| VAD detection | ~50ms |
| Whisper ASR | ~800ms |
| Semantic cache lookup | ~1ms |
| LLM processing | ~200ms |
| Cartesia TTS | ~100ms |
| WebSocket delivery | ~50ms |
| **Total (cache miss)** | **~1200ms** |
| **Total (cache hit)** | **~150ms** |

### Throughput
- VAD: Real-time (30ms audio chunks)
- ASR: 1 request at a time (queued)
- TTS: Streams chunks (40ms to first audio)
- Database: SQLite (concurrent read/write via WAL)

### Reliability
- Retry logic with exponential backoff on Recall.ai API errors
- Graceful degradation if voice initialization fails
- Fallback from WebSocket to Recall.ai API for audio delivery
- Fallback from Silero VAD to energy-based VAD
- Fallback from Cartesia TTS to OpenAI TTS

### Storage
- Transcripts cached in database (text only)
- Voice cache limited to 100KB per audio clip
- Interaction history limited to 1000 (FIFO eviction)
- Semantic cache max 500 entries with LRU eviction

---

## 12. Security Considerations

### Authentication
- **Recall.ai API:** Token-based in Authorization header
- **Webhooks:** HMAC signature verification (SHA-256) via X-Recall-Signature header
- **Voice queries:** Use existing user context from Zoom

### Input Validation
- Meeting URLs validated against whitelist (Zoom, Teams, Meet domains)
- Input sanitized for voice synthesis (markdown removed, max 400 chars)
- SQL queries use parameterized statements (SQLite)

### Rate Limiting
- Meeting joins: 5 per hour (configurable)
- Chat queries: 20 per hour (configurable)
- Checked via database timestamp tracking

### Data Isolation
- Meeting records tied to requesting user
- Transcripts associated with specific meeting_id
- No cross-meeting data leakage

---

## 13. Testing Hooks

### Test Endpoints
- `POST /api/voice/tts` - Generate speech from text (no meeting required)
- `POST /api/voice/query` - Text query with full processing
- `POST /api/meeting/join` - Dry run meeting join

### Mock Data
- Voice pipeline accepts custom query_handler function
- Can pass echo handler for testing: `lambda text: f"I heard: {text}"`
- VoicePipeline configurable without Recall.ai API
