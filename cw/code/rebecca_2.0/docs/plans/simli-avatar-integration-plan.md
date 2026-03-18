# Simli Avatar Integration Plan

## Executive Summary

Enable the Simli animated avatar feature that is currently configured but not fully integrated. The environment has `AVATAR_ENABLED=true` and `SIMLI_API_KEY` set, but the video frame pipeline from Simli to the avatar webpage is incomplete.

## Current State Analysis

### What's Working
- Environment configured: `AVATAR_ENABLED=true`, `SIMLI_API_KEY`, `SIMLI_FACE_ID`
- SimliClient class exists with WebSocket and REST API support
- AvatarSessionManager class exists and is instantiated in app.py
- Voice pipeline sends audio via WebSocket to avatar page
- Avatar routes serve the avatar webpage

### What's Not Working (Gaps Identified)
1. **SimliClient WebSocket Not Fully Wired**: The `connect_websocket()` method exists but isn't called during voice responses
2. **Video Frame Routing Missing**: `AvatarSessionManager.send_audio_for_avatar()` sends audio to Simli but video frames aren't routed to the webpage
3. **Avatar Page Video Stub**: The avatar HTML has a comment "Video frame handling would go here" - video display not implemented
4. **No Simli Session Lifecycle**: Avatar session isn't started when bot joins meeting with avatar

## Rate Limit Strategy (CRITICAL)

Per CLAUDE.md:
- **Simli: 2 calls max** (1 reserved for health check = **1 usable call**)
- **Testing Approach**:
  - All unit tests use MockSimliClient (0 real calls)
  - One manual integration test with explicit rate limit check
  - Add rate limit tracking to .claude/session_limits.json

## Implementation Plan

### Phase 1: Fix Core Integration (No API Calls)

#### 1.1 Wire SimliClient into Voice Response Flow
**File**: `src/voice/voice_pipeline.py`

Add integration point in `respond_to_query()` to send audio to Simli:
```python
# After TTS generation, send to avatar if available
if self._avatar_session_manager and self._avatar_session_manager.is_active:
    self._avatar_session_manager.send_audio_for_avatar(
        audio_data=tts_result.audio_data,
        text=voice_text,
        sample_rate=getattr(self.tts_client, 'sample_rate', 24000)
    )
```

#### 1.2 Start Avatar Session on Meeting Join
**File**: `src/meeting/meeting_handler.py`

In `join_meeting()`, start avatar session when output_media_url is configured:
```python
if output_media_url and self._avatar_session_manager:
    self._avatar_session_manager.start_session(meeting_id)
```

#### 1.3 Route Video Frames to WebSocket
**File**: `src/avatar/avatar_session.py`

Modify `_handle_video_frame()` to send frames via WebSocket:
```python
def _handle_video_frame(self, frame: bytes):
    # Existing metrics update
    self._metrics["total_video_frames"] += 1

    # Send to avatar webpage via WebSocket
    from .websocket_manager import get_avatar_ws_manager
    manager = get_avatar_ws_manager(self.logger)
    if self._meeting_id:
        manager.send_video_frame(self._meeting_id, frame)
```

#### 1.4 Add Video Frame WebSocket Message Type
**File**: `src/avatar/websocket_manager.py`

Add `send_video_frame()` method:
```python
def send_video_frame(self, session_id: str, frame: bytes) -> bool:
    """Send video frame to avatar webpage."""
    with self._lock:
        resolved_id = self._resolve_id(session_id)
        conn = self._connections.get(resolved_id)
        if not conn:
            return False

    try:
        b64_frame = base64.b64encode(frame).decode('utf-8')
        message = json.dumps({
            "type": "video_frame",
            "data": b64_frame,
            "timestamp": time.time()
        })
        conn.ws.send(message)
        return True
    except Exception as e:
        self.logger.error(f"Failed to send video frame: {e}")
        return False
```

### Phase 2: Implement Avatar Page Video Display

#### 2.1 Update Static Avatar HTML
**File**: `src/avatar/static/avatar.html`

Add video frame handling in the WebSocket message handler:
```javascript
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'video_frame') {
        // Display video frame
        const img = new Image();
        img.onload = () => {
            avatarImage.style.display = 'none';
            avatarCanvas.style.display = 'block';
            ctx.drawImage(img, 0, 0, avatarCanvas.width, avatarCanvas.height);
        };
        img.src = 'data:image/jpeg;base64,' + data.data;
    }
    // ... existing audio/state handling
};
```

#### 2.2 Add Canvas Element to Avatar Page
Add a canvas element for rendering video frames alongside the existing img element.

### Phase 3: Testing (Rate-Limit Safe)

#### 3.1 Unit Tests with MockSimliClient
**File**: `tests/test_simli_integration.py`

```python
def test_avatar_session_sends_to_simli(mock_simli_client):
    """Test that audio is sent to Simli during voice response."""
    # Uses MockSimliClient - 0 real API calls

def test_video_frame_routing():
    """Test video frames are routed to WebSocket."""
    # Uses mock frames - 0 real API calls

def test_avatar_page_receives_frames():
    """Test avatar page WebSocket receives video frames."""
    # Uses mock WebSocket - 0 real API calls
```

#### 3.2 Integration Test with Rate Limit Guard
**File**: `tests/integration/test_simli_live.py`

```python
@pytest.mark.skip(reason="Requires manual execution - uses Simli API quota")
def test_simli_live_avatar():
    """
    MANUAL TEST - Run only when needed.

    Rate limit: Simli allows 2 calls max per session.
    This test uses 1 call. Reserve 1 for health checks.
    """
    # Check .claude/session_limits.json before proceeding
    limits = load_session_limits()
    if limits.get("simli", 0) >= 1:
        pytest.skip("Simli rate limit reached - cannot run live test")

    # Run actual Simli test
    # ...

    # Increment limit after test
    increment_session_limit("simli")
```

### Phase 4: Cleanup and Documentation

#### 4.1 Update Session Limits Tracking
Ensure `.claude/session_limits.json` is updated after any Simli API call.

#### 4.2 Add Logging for Debug
Add comprehensive logging at each step of the video pipeline for debugging.

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Rate limit exceeded | All tests use mocks; live test has guard |
| WebSocket connection failures | Graceful fallback to static image |
| Simli API errors | Circuit breaker in SimliClient |
| Large video frames cause lag | Bounded queue (already implemented) |

## Success Criteria

1. Avatar session starts when bot joins meeting with avatar
2. Audio from TTS is sent to Simli for lip-sync
3. Video frames from Simli are displayed on avatar page
4. All unit tests pass with mocks (0 API calls)
5. Integration test can be manually run when needed

## Files to Modify

1. `src/voice/voice_pipeline.py` - Wire avatar into response flow
2. `src/meeting/meeting_handler.py` - Start avatar session on join
3. `src/avatar/avatar_session.py` - Route video frames to WebSocket
4. `src/avatar/websocket_manager.py` - Add video frame message type
5. `src/avatar/static/avatar.html` - Implement video display
6. `tests/test_simli_integration.py` - New mock tests
7. `tests/integration/test_simli_live.py` - New guarded integration test

## Estimated Changes

- ~150 lines of new code
- ~50 lines of test code
- 0 Simli API calls during implementation
- 1 Simli API call for optional live test

---

## Adversarial Council Review (2026-01-12)

### Assessment: NEEDS_WORK

### BLOCKER Issues Identified

1. **Queue Blocking Race Condition** (SimliClient)
   - `_video_queue.put()` blocks when full, freezing WebSocket thread
   - **Fix**: Use `put_nowait()` with exception handling and overflow policy

2. **Missing Circuit Breaker** (SimliClient)
   - No circuit breaker on Simli API calls
   - **Fix**: Wrap API calls with CircuitBreaker and integrate with session_limits

3. **Incomplete Video Frame Protocol**
   - `send_video_frame()` doesn't exist in WebSocketManager
   - Avatar HTML has placeholder "Video frame handling would go here"
   - **Fix**: Define complete protocol and implement both ends

### MAJOR Issues Identified

4. **Memory Leak in Error Counter**
   - `_metrics["errors"]` grows unboundedly
   - **Fix**: Add error threshold to trigger session restart

5. **Thread Safety Gap in VoicePipeline**
   - Concurrent `respond_to_query()` calls can corrupt avatar state
   - **Fix**: Add request serialization with queue/lock

6. **WebSocket Buffer Overflow**
   - Base64 video frames: 65-130KB each at 30fps = 2-4MB/s
   - **Fix**: Use binary WebSocket messages instead of base64 JSON

7. **Inadequate Simli Error Recovery**
   - Session enters ERROR state with no reconnection
   - **Fix**: Add reconnection logic with exponential backoff

### Council Recommendations Incorporated

- Use `put_nowait()` with drop-oldest policy for frame queue
- Add `send_video_frame_binary()` using WebSocket opcode 0x2
- Add CSP header to avatar page
- Implement error threshold (10 consecutive errors → restart)
- Add voice response queue for serialization
