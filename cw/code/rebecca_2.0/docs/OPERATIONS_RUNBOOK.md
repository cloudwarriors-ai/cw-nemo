# QA Bot Operations Runbook

This runbook covers operational procedures for monitoring, maintaining, and troubleshooting the QA Continuity Bot.

## Table of Contents

1. [Health Monitoring](#health-monitoring)
2. [Common Issues](#common-issues)
3. [Incident Response](#incident-response)
4. [Maintenance Procedures](#maintenance-procedures)
5. [Scaling](#scaling)
6. [Backup & Recovery](#backup--recovery)

---

## Health Monitoring

### Health Check Endpoint

The bot exposes a health endpoint at `/health`:

```bash
# Basic health check
curl https://your-domain.com/health

# Detailed health check (includes dependencies)
curl https://your-domain.com/health?detailed=true
```

### Expected Healthy Response

```json
{
  "status": "ok",
  "timestamp": 1704067200.0,
  "version": "1.0.0",
  "config": {
    "github_configured": true,
    "repos": ["org/repo1", "org/repo2"]
  },
  "dependencies": {
    "database": {"status": "ok"},
    "github": {"status": "ok"},
    "recall_ai": {"status": "configured"},
    "voice": {"status": "configured"},
    "avatar": {"status": "not_configured"}
  }
}
```

### Monitoring Checklist

| Check | Frequency | Alert Threshold |
|-------|-----------|-----------------|
| Health endpoint responds | Every 1 min | 3 consecutive failures |
| Response time < 500ms | Every 1 min | > 2 seconds |
| GitHub rate limit | Every 5 min | < 100 remaining |
| Database size | Daily | > 500MB |
| Memory usage | Every 1 min | > 80% |
| Error rate | Every 5 min | > 5% of requests |

### Log Monitoring

Key log patterns to watch:

```bash
# Errors requiring attention
grep -E "ERROR|CRITICAL|Traceback" /var/log/qa-bot.log

# Rate limiting warnings
grep "rate limit" /var/log/qa-bot.log

# Authentication failures
grep "401\|unauthorized" /var/log/qa-bot.log
```

---

## Common Issues

### Issue: Bot Not Responding to Messages

**Symptoms:**
- Messages to bot get no response
- Health check passes

**Diagnosis:**
1. Check Zoom webhook endpoint validation
2. Verify `ZOOM_BOT_TOKEN` is correct
3. Check for HMAC signature failures in logs

**Resolution:**
```bash
# Check recent webhook logs
docker logs qa-continuity-bot | grep -i zoom

# Verify environment variables
docker exec qa-continuity-bot env | grep ZOOM
```

---

### Issue: GitHub Issues Not Loading

**Symptoms:**
- "Unable to fetch issues" responses
- Cache appears stale

**Diagnosis:**
1. Check GitHub token validity
2. Verify rate limits
3. Check repository access

**Resolution:**
```bash
# Check rate limit status
curl -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/rate_limit

# Test API access
curl -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$GITHUB_ORG/$REPO/issues?state=open
```

**Fix: Regenerate GitHub Token**
1. Go to GitHub Settings > Developer Settings > Personal Access Tokens
2. Generate new token with `repo` scope
3. Update `GITHUB_TOKEN` in `.env`
4. Restart container: `docker-compose restart qa-bot`

---

### Issue: Database Locked

**Symptoms:**
- "database is locked" errors
- Slow response times
- Timeout errors

**Diagnosis:**
```bash
# Check database file locks
lsof data/qa_bot.db

# Check database integrity
sqlite3 data/qa_bot.db "PRAGMA integrity_check;"
```

**Resolution:**
```bash
# Stop container
docker-compose stop qa-bot

# Backup current database
cp data/qa_bot.db data/qa_bot.db.backup

# Check and repair
sqlite3 data/qa_bot.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Restart container
docker-compose start qa-bot
```

---

### Issue: High Memory Usage

**Symptoms:**
- OOM kills in Docker
- Slow performance
- Container restarts

**Diagnosis:**
```bash
# Check container memory
docker stats qa-continuity-bot

# Check Python memory
docker exec qa-continuity-bot python -c "import sys; print(sys.getsizeof([]))"
```

**Resolution:**
1. Restart the container to clear memory
2. Check for memory leaks in issue cache
3. Increase container memory limit if needed

```bash
# Force restart
docker-compose restart qa-bot

# Update memory limit in docker-compose.yml
deploy:
  resources:
    limits:
      memory: 1G  # Increase from 512M
```

---

### Issue: Meeting Bot Not Joining

**Symptoms:**
- "Failed to join meeting" errors
- Bot never appears in meeting

**Diagnosis:**
1. Check Recall.ai API key validity
2. Verify meeting URL format
3. Check meeting permissions

**Resolution:**
```bash
# Check Recall.ai status
curl -H "Authorization: Token $RECALL_API_KEY" \
  https://api.recall.ai/api/v1/bot/

# Verify API key works
curl -H "Authorization: Token $RECALL_API_KEY" \
  https://api.recall.ai/api/v1/account/
```

---

### Issue: Voice/Avatar Not Working

**Symptoms:**
- No voice responses in meetings
- Avatar not rendering

**Diagnosis:**
1. Check Cartesia/Simli API keys
2. Verify WebRTC connectivity
3. Check audio format compatibility

**Resolution:**
```bash
# Test TTS API
curl -X POST https://api.cartesia.ai/v1/audio/speech \
  -H "Authorization: Bearer $CARTESIA_API_KEY" \
  -d '{"text": "test"}'

# Check Simli connection
curl https://api.simli.ai/health \
  -H "Authorization: Bearer $SIMLI_API_KEY"
```

---

## Incident Response

### Severity Levels

| Level | Description | Response Time | Escalation |
|-------|-------------|---------------|------------|
| P1 | Bot completely down | 15 min | Immediate |
| P2 | Major feature broken | 1 hour | Within 2 hours |
| P3 | Minor feature broken | 4 hours | Next business day |
| P4 | Cosmetic/minor issue | 24 hours | As capacity allows |

### P1 Incident Procedure

1. **Acknowledge** - Confirm incident within 15 minutes
2. **Diagnose** - Check health endpoint, logs, and metrics
3. **Communicate** - Post status update to team
4. **Resolve** - Apply fix or rollback
5. **Verify** - Confirm service restored
6. **Document** - Create incident report

### Rollback Procedure

```bash
# List recent images
docker images qa-continuity-bot

# Stop current container
docker-compose down

# Update image tag to previous version
# Edit docker-compose.yml: image: qa-continuity-bot:previous-tag

# Start with previous version
docker-compose up -d

# Verify health
curl https://your-domain.com/health
```

---

## Maintenance Procedures

### Planned Maintenance Window

1. **Announce** - Notify team 24 hours in advance
2. **Prepare** - Test changes in staging
3. **Backup** - Create database backup
4. **Execute** - Perform maintenance
5. **Verify** - Run health checks
6. **Announce** - Confirm completion

### Database Maintenance

```bash
# Weekly: Vacuum database
docker exec qa-continuity-bot sqlite3 /app/data/qa_bot.db "VACUUM;"

# Weekly: Analyze tables
docker exec qa-continuity-bot sqlite3 /app/data/qa_bot.db "ANALYZE;"

# Monthly: Check integrity
docker exec qa-continuity-bot sqlite3 /app/data/qa_bot.db "PRAGMA integrity_check;"
```

### Log Rotation

Logs are automatically rotated by Docker. Configure retention:

```yaml
# docker-compose.yml
services:
  qa-bot:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### Certificate Renewal

If using Let's Encrypt with nginx:

```bash
# Test renewal
certbot renew --dry-run

# Force renewal (if needed)
certbot renew --force-renewal

# Reload nginx
nginx -s reload
```

---

## Scaling

### Horizontal Scaling

The bot is designed for single-instance operation due to:
- SQLite database (single writer)
- In-memory issue cache
- Meeting session state

For horizontal scaling, consider:
1. Switch to PostgreSQL for database
2. Use Redis for cache and session state
3. Run multiple bot instances behind load balancer

### Vertical Scaling

Adjust container resources:

```yaml
# docker-compose.yml
deploy:
  resources:
    limits:
      cpus: '2.0'      # Up from 1.0
      memory: 1024M    # Up from 512M
    reservations:
      cpus: '0.5'
      memory: 256M
```

### Performance Tuning

```yaml
# Increase Gunicorn workers
command: >
  gunicorn
    --bind 0.0.0.0:5000
    --workers 4           # 2 * CPU cores + 1
    --threads 4
    --timeout 120
    --factory
    src.bot.app:create_app
```

---

## Backup & Recovery

### Backup Procedure

```bash
# Daily backup script
#!/bin/bash
BACKUP_DIR="/backups/qa-bot"
DATE=$(date +%Y%m%d_%H%M%S)

# Backup database
docker exec qa-continuity-bot sqlite3 /app/data/qa_bot.db ".backup /app/data/backup.db"
docker cp qa-continuity-bot:/app/data/backup.db $BACKUP_DIR/qa_bot_$DATE.db

# Backup environment (without secrets)
grep -v "TOKEN\|KEY\|SECRET" .env > $BACKUP_DIR/env_$DATE.txt

# Keep last 7 days
find $BACKUP_DIR -mtime +7 -delete
```

### Recovery Procedure

```bash
# Stop container
docker-compose down

# Restore database
cp /backups/qa-bot/qa_bot_YYYYMMDD.db data/qa_bot.db

# Restore environment
cp /backups/qa-bot/env_YYYYMMDD.txt .env
# Re-add secrets manually

# Start container
docker-compose up -d

# Verify
curl https://your-domain.com/health
```

### Disaster Recovery

1. **Data Recovery**
   - Restore from most recent backup
   - GitHub issues are re-cached automatically
   - Meeting history may be lost

2. **Configuration Recovery**
   - `.env` template available in `.env.example`
   - Re-obtain API keys from respective services
   - Re-validate Zoom webhook URL

3. **Full Rebuild**
   ```bash
   git clone https://github.com/your-org/qa-continuity-app
   cd qa-continuity-app
   cp .env.example .env
   # Fill in .env with credentials
   docker-compose up -d --build
   ```

---

## Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| Primary On-Call | [Your Team] | [Slack/PagerDuty] |
| Secondary On-Call | [Backup Contact] | [Slack/PagerDuty] |
| Engineering Lead | [Name] | [Email] |

## Runbook Maintenance

- Review runbook quarterly
- Update after each incident
- Test backup/recovery procedures monthly
- Keep API documentation links current
