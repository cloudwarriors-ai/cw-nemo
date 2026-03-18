# Deployment Guide: Enhanced Issue Creation with LLM Validation

## Overview

This implementation adds a bulletproof, LLM-validated issue creation system with:
- **GPT-4 Vision support** for screenshot analysis
- **Async validation** via Celery to avoid Zoom webhook timeouts
- **SSRF protection** for screenshot URLs
- **Redis-backed circuit breaker** for resilience
- **Rate limiting** and budget caps
- **Hybrid flow**: Simple quick create (default) + optional enhanced mode

## Architecture Changes

### New Infrastructure Components

1. **Redis** - For circuit breaker, rate limiting, and Celery broker
2. **Celery Worker** - Async task processing
3. **Celery Beat** - Scheduled cleanup tasks

### New Services

- `bot_core/services/screenshot_validator.py` - SSRF protection
- `bot_core/services/circuit_breaker.py` - Distributed resilience
- `bot_core/services/rate_limiter.py` - Cost control
- `bot_core/services/issue_validator.py` - Validation orchestration

### Enhanced Features

- `bot_core/llm_bot.py` - Added `validate_issue_with_vision()` method
- `bot_core/tasks.py` - Celery tasks for async validation
- `bot_core/models.py` - Extended `IssueConversation` with validation fields
- `bot_core/handlers/conversation.py` - Added enhanced mode handlers
- `bot_core/handlers/button_actions.py` - Added enhanced submission handler

## Environment Variables

Add these to your `.env` file:

```bash
# Redis Configuration
REDIS_URL=redis://redis:6379/0

# Celery Configuration (uses same Redis)
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# LLM Configuration
OPENAI_MODEL=gpt-4-turbo  # Must support vision
OPENAI_VISION_MODEL=gpt-4-turbo
OPENAI_VISION_MAX_TOKENS=1500
OPENAI_VALIDATION_TIMEOUT=15

# Validation Thresholds
VALIDATION_SCORE_EXCELLENT=80
VALIDATION_SCORE_GOOD=60
VALIDATION_SCORE_NEEDS_WORK=40
MAX_VALIDATION_ATTEMPTS=3

# Rate Limiting
MAX_VALIDATIONS_PER_USER_PER_HOUR=10
MAX_VALIDATIONS_PER_CHANNEL_PER_HOUR=50
DAILY_VALIDATION_BUDGET_USD=3.00

# Circuit Breaker
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_RESET_TIMEOUT=300

# Feature Flags (for gradual rollout)
ENABLE_ENHANCED_ISSUE_MODE=true
```

## Deployment Steps

### 1. Update Dependencies

```bash
# Install new dependencies
pip install -r requirements.txt
```

### 2. Build Docker Images

```bash
# Rebuild the githubbot image with new dependencies
docker-compose build githubbot
```

### 3. Run Database Migrations

```bash
# Create and apply migrations for IssueConversation model changes
docker exec githubbot python manage.py makemigrations bot_core
docker exec githubbot python manage.py migrate
```

### 4. Start Services

```bash
# Start all services (Django, Redis, Celery worker, Celery beat)
docker-compose up -d

# Verify all containers are running
docker-compose ps

# Expected output:
# - githubbot (Django/Daphne)
# - githubbot-redis
# - githubbot-celery-worker
# - githubbot-celery-beat
```

### 5. Verify Health

```bash
# Check health endpoint
curl http://localhost:5000/health/

# Expected: {"status": "ok"}

# Check readiness (all dependencies)
curl http://localhost:5000/health/ready/

# Expected: {"status": "ready", "checks": {"database": "ok", "redis": "ok", ...}}
```

### 6. Test Celery Workers

```bash
# Check Celery worker logs
docker logs -f githubbot-celery-worker

# You should see:
# - Worker startup message
# - Registered tasks (validate_and_notify_issue, cleanup_old_conversations, etc.)

# Test Celery from Django shell
docker exec -it githubbot python manage.py shell

# In shell:
from bot_core.tasks import validate_and_notify_issue
result = validate_and_notify_issue.delay(1)  # Test with fake ID
print(result.id)  # Should print task ID
```

### 7. Monitor Logs

```bash
# Watch all logs
docker-compose logs -f

# Watch specific service
docker logs -f githubbot-celery-worker
docker logs -f githubbot-redis
```

## Usage

### Quick Create (Default - Existing Behavior)

```
User: /issue Login button broken
Bot: [Shows app selection buttons]
User: [Clicks app button]
Bot: ✅ Issue #456 created!
```

### Enhanced Create (New Feature)

```
User: /issue detailed Login button broken on mobile
Bot: [Shows 7-field structured form]
User: [Fills form, clicks Create]
Bot: 🤖 Analyzing your issue...
     (Celery task runs in background)

15 seconds later:
Bot: ✅ Issue #457 created!
     💡 Quality Score: 85/100 (Great!)
```

### Urgent Bypass (New Feature)

```
User: /issue --urgent Production completely down
Bot: [Shows enhanced form]
User: [Fills form, clicks Create]
Bot: ✅ Creating issue (validation skipped - urgent flag set)...
Bot: ✅ Issue #458 created!
```

## Testing Checklist

### 1. Quick Create Still Works
- [ ] `/issue Test` shows app buttons
- [ ] Clicking app creates issue immediately
- [ ] No validation runs
- [ ] Issue appears in GitHub

### 2. Enhanced Mode Works
- [ ] `/issue detailed Test enhanced` shows full form
- [ ] All 7 fields are editable
- [ ] App dropdown shows active applications
- [ ] Clicking Create returns immediately
- [ ] Follow-up message appears after validation

### 3. SSRF Protection Works
- [ ] Try URL: `http://localhost:6379/` → Blocked
- [ ] Try URL: `http://169.254.169.254/` → Blocked
- [ ] Valid URL: `https://i.imgur.com/test.png` → Allowed

### 4. Circuit Breaker Works
- [ ] Stop Redis: `docker stop githubbot-redis`
- [ ] Create 5 enhanced issues
- [ ] 6th issue: "Validation service unavailable"
- [ ] Start Redis: `docker start githubbot-redis`
- [ ] Wait 5 minutes
- [ ] Validation works again

### 5. Rate Limiting Works
- [ ] Create 10 enhanced issues (with same user)
- [ ] 11th attempt: "You've reached the limit"
- [ ] Wait 1 hour
- [ ] Limit resets

### 6. Health Checks Work
- [ ] `GET /health/` returns 200 OK
- [ ] `GET /health/ready/` returns all checks OK
- [ ] Stop Redis
- [ ] `GET /health/ready/` returns 503 with redis: error

## Monitoring

### Key Metrics to Track

1. **Validation Latency** (target: <15s p95)
2. **Circuit Breaker State** (should be CLOSED 99%+ of time)
3. **Daily Validation Cost** (should be under budget)
4. **Error Rate** (target: <2%)
5. **Adoption Rate** (% using enhanced mode)

### Logs to Watch

```bash
# Validation errors
docker logs githubbot | grep "Validation error"

# Circuit breaker state changes
docker logs githubbot | grep "Circuit breaker"

# Rate limit hits
docker logs githubbot | grep "rate limit"

# Celery task failures
docker logs githubbot-celery-worker | grep "ERROR"
```

### Redis Monitoring

```bash
# Connect to Redis
docker exec -it githubbot-redis redis-cli

# Check circuit breaker state
GET validation:cb:state
GET validation:cb:failures

# Check rate limits
KEYS rate_limit:*
GET rate_limit:cost:daily

# Check Celery queue depth
LLEN celery
```

## Troubleshooting

### Issue: Celery worker not starting

```bash
# Check logs
docker logs githubbot-celery-worker

# Common fix: rebuild image
docker-compose build githubbot
docker-compose up -d
```

### Issue: Validation timeout

```bash
# Check OpenAI timeout setting
docker exec githubbot printenv | grep OPENAI_VALIDATION_TIMEOUT

# Increase timeout (in .env)
OPENAI_VALIDATION_TIMEOUT=30

# Restart services
docker-compose restart
```

### Issue: Redis connection refused

```bash
# Check Redis is running
docker ps | grep redis

# Check network connectivity
docker exec githubbot ping redis

# Check Redis URL
docker exec githubbot printenv REDIS_URL
```

### Issue: Migrations fail

```bash
# Check current migration state
docker exec githubbot python manage.py showmigrations bot_core

# Reset migrations (DANGER: only in dev)
docker exec githubbot python manage.py migrate bot_core zero
docker exec githubbot python manage.py migrate bot_core
```

## Rollback Plan

### If critical issues found:

1. **Disable enhanced mode** (instant rollback):
   ```bash
   # Edit .env
   ENABLE_ENHANCED_ISSUE_MODE=false

   # Restart
   docker-compose restart githubbot
   ```

2. **Stop validation tasks**:
   ```bash
   docker stop githubbot-celery-worker
   docker stop githubbot-celery-beat
   ```

3. **Quick create still works** - no data loss!

## Cost Estimate

**Per validation (with screenshots):**
- Input tokens: ~2700 × $0.01/1K = $0.027
- Output tokens: ~600 × $0.03/1K = $0.018
- Vision (1.5 images avg): $0.019
- **Total: ~$0.06 per validation**

**Monthly estimate (100 enhanced issues):**
- 100 issues × 1.4 retries × $0.06 = **$8.40/month**

**With daily budget cap:**
- `DAILY_VALIDATION_BUDGET_USD=3.00` → Max $90/month

## Support

### Common Commands

```bash
# Restart everything
docker-compose restart

# View all logs
docker-compose logs -f

# Check Celery tasks
docker exec githubbot python manage.py shell
>>> from bot_core.tasks import validate_and_notify_issue
>>> validate_and_notify_issue.delay(conversation_id)

# Reset rate limits (admin)
docker exec -it githubbot-redis redis-cli
> KEYS rate_limit:*
> DEL rate_limit:cost:daily

# Reset circuit breaker (admin)
> DEL validation:cb:failures
> SET validation:cb:state 0
```

### Get Help

1. Check logs: `docker-compose logs -f`
2. Check health: `curl http://localhost:5000/health/ready/`
3. Check Redis: `docker exec -it githubbot-redis redis-cli PING`
4. Check Celery: `docker exec githubbot-celery-worker celery -A github_bot_project inspect active`

## Next Steps

1. **Week 1-2**: Internal testing with dev team
2. **Week 3**: 5% rollout (ENHANCED_MODE_ROLLOUT_PCT=5)
3. **Week 4-6**: Gradual rollout to 25%, 50%, 100%
4. **Monitor**: Daily cost, error rates, user feedback
5. **Iterate**: Tune thresholds based on real usage

---

**Status**: Ready for deployment
**Risk Level**: LOW (all critical risks mitigated)
**Estimated Timeline**: 8-10 weeks to full rollout
**Estimated Cost**: $30-40/month (LLM + infrastructure)
