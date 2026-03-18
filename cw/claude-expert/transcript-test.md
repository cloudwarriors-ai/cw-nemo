# Transcript-to-Order E2E Test Runbook

## Prerequisites

1. **Bighead running** on `proxy` network:
   ```bash
   cd /root/web/bighead && docker-compose -f docker-compose.cpu.yml up -d
   ```
   If bighead isn't resolving from openclaw, reconnect it:
   ```bash
   docker network connect proxy bighead-bighead-1 --alias bighead
   ```

2. **Moltbot running**:
   ```bash
   cd /root/web/moltbot && docker-compose -f docker-compose.dev.yml up -d
   ```

3. **Transcript repo** cloned at `.data/openclaw/workspace/memory/transcript-simulation/`
   (auto-cloned by the bot on first `/transcript-order` run)

4. **ZW2 credentials** in `.env`: `ZW2_URL`, `ZW2_USERNAME`, `ZW2_PASSWORD`

## Running the Test

The e2e test script lives at `scripts/tests/empire-e2e.mjs` and is mounted into the container at `/app/tests/`.

```bash
docker exec openclaw node /app/tests/empire-e2e.mjs
```

This takes ~2-3 minutes (3 LLM calls to Rebecca + 12 API calls to ZW2).

## What the Test Does

1. **Extract** — Reads the Empire Auto Partners transcript (21k chars), sends to `POST /api/analyze/transcript` on Bighead/Rebecca. Gets structured order data back.

2. **Grade** — Checks extracted data against all 36 required ZW2 fields. Reports which were found in the transcript vs missing.

3. **Save** — Stores extraction in SQLite DB at `/root/.openclaw/data/zw2-extractions.db`.

4. **Technical Followup** — Asks Rebecca to clarify AR/CQ split, common area licenses, and type corrections via `POST /api/analyze/followup`.

5. **Customer Responses** — Supplies test answers (from reference SOW) for fields never discussed in the transcript (contact info, billing, hardware, go-live dates).

6. **Submit to ZW2** — Creates order, submits all 10 sections. On failure, routes the API error back to Rebecca for correction and retries once.

7. **Generate SOW** — Triggers SOW generation on the completed order.

## Expected Results

```
TRANSCRIPT COMPLETENESS: ~64% (23/36 fields from transcript alone)
Missing: 13 fields (contact info, billing, hardware, go-live dates)
Sections: 10/10 OK
SOW: Generated
RESULT: PASS
```

## Test Answers (Reference SOW Values)

These simulate what the customer would provide on a live call:

| Field | Value | Source |
|-------|-------|--------|
| order_name | Empire Auto Partners (ZP + ZCC) | SOW header |
| company_address | 15 Jackson Rd., Totowa, New Jersey | SOW |
| company_website | https://www.empireautoparts.com | SOW |
| decision_maker_phone | 9737724206 | SOW |
| billing_same_as_decision_maker | true | SOW |
| billing_contact_name | Charles Hollien | SOW |
| billing_contact_email | chollien@empireautoparts.com | SOW |
| billing_contact_phone | 9737724206 | SOW |
| common_area_licenses | 0 | SOW (none listed) |
| physical_phones_in_use | true | SOW |
| reprovisioning_needed | false | SOW |
| handset_reprovisioning_count | 0 | SOW |
| go_live_events | ZP: 2026-04-06, ZCC: 2026-05-04 | Estimated |

## Key Extraction Wins (Fixed from Earlier Runs)

| Field | Before | Now | Fix |
|-------|--------|-----|-----|
| zoom_phone_licenses | 900 (fudged +50 CAP) | 850 | Prompt: don't fudge technical fields |
| webchat_channel_needed | missing | true | Prompt: explicit ZCC channel checklist |
| sso_type | "SAML 2.0" (rejected) | "basic" | Prompt: use API enum values |
| zcc_intent | "new_deployment" (string) | true (bool) | Prompt: boolean fields |
| physical_phones_in_use | 800 (int) | true (bool) | Prompt: boolean fields |

## Known Remaining Issues

- **AR/CQ split**: Rebecca extracts 19 for both (transcript says "19 total combined"). Followup corrects to 1+18=19. Not ideal but functional.
- **DB connections/dips**: Rebecca still misses these (should be 2 each per reference SOW). Needs prompt improvement.
- **2 fields still missing after followups**: Rebecca occasionally leaves minor fields unfilled. The submission still succeeds because the API has defaults.

## Debugging

```bash
# Check bighead is reachable
docker exec openclaw curl -s http://bighead:8000/health

# Check Rebecca's prompt config
curl -s http://localhost:8015/api/config/transcript-prompt | python3 -m json.tool

# View extraction DB
docker exec openclaw node -e "
  const {DatabaseSync} = require('node:sqlite');
  const db = new DatabaseSync('/root/.openclaw/data/zw2-extractions.db');
  const rows = db.prepare('SELECT id, customer_name, order_id, status, followup_count FROM extractions ORDER BY id DESC LIMIT 5').all();
  console.table(rows);
"

# View last extraction details
cat /tmp/empire-final-extract.json | python3 -m json.tool

# View test report
cat /tmp/empire-e2e-report.txt
```

## Adding More Customers

Copy `scripts/tests/empire-e2e.mjs`, change:
- Transcript file path (line reading `readFileSync`)
- `TEST_ANSWERS` object (source from that customer's reference SOW)
- Report title

Available transcripts in `memory/transcript-simulation/`:
- Perma-Seal, K&L Wine Merchants, Von Braun Brewing, Empire Auto Partners
- 26 more untested customers

## Test History

| Date | Order # | Result | Notes |
|------|---------|--------|-------|
| 2026-02-12 | #364 | PASS | Perma-Seal (100% match) |
| 2026-02-12 | #365 | PASS | K&L Wine (100% match) |
| 2026-02-12 | #366 | PASS | Von Braun (100% match) |
| 2026-02-12 | #367 | PASS | Empire Auto (88% match, first run) |
| 2026-02-13 | #384 | PASS | Empire Auto (clean, all 10/10 first attempt) |
