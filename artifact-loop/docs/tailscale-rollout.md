# Artifact Loop Tailscale Rollout

Artifact Loop over Tailscale is split into three planes:

- Coordination plane: `artifact-loop`
- Runtime plane: OpenClaw gateway / NemoClaw runtime
- Transport: Tailscale

Stage 1 is implemented here. Stages 2 and 3 are intentionally deferred.

## Runtime Gate Boundary

Do not start Stage 2 or Stage 3 because this repo branch says they are "next."

They remain blocked until Stage 1 is proven on Doug's actual target host.

The runtime track becomes eligible only after all of the following are true:

- Doug has pulled branch `codex/session-source-visibility-20260319`
- Doug's machine passes `start-artifact-loop-hub.sh`, `check-artifact-loop-hub.sh`, `configure-tailscale-artifact-loop-proxy.sh`, and `check-tailscale-artifact-loop-proxy.sh`
- a teammate machine completes `bash ./scripts/scenarios/tailscale_shared_coordination_v1.sh` against the tailnet URL

Until those conditions are met:

- Artifact Loop remains the coordination truth
- OpenClaw remains the runtime plane
- Tailscale remains transport only

## Stage 1 Prerequisites

On Doug's host:

- Tailscale is installed and authenticated to the team tailnet
- `tailscale serve` is available
- Node and the `artifact-loop` repo are present
- Doug's host is the only machine running scheduled briefs for the shared hub

Recommended defaults:

- Local hub bind: `127.0.0.1:4080`
- Tailnet hub URL: `https://nemoclaw.tailcc6c5f.ts.net:4443`
- Stable data dir: `~/.artifact-loop/team-hub`

Environment overrides used by the ops scripts:

- `ARTIFACT_LOOP_HUB_DATA_DIR`
- `ARTIFACT_LOOP_HUB_HOST`
- `ARTIFACT_LOOP_HUB_PORT`
- `ARTIFACT_LOOP_HUB_TAILSCALE_HTTPS_PORT`
- `ARTIFACT_LOOP_HUB_URL`

## Stage 1A — Doug Host Local Hub

Start the local hub:

```bash
cd /Users/chadsimon/chad_bot_attempt/nemoclaw/artifact-loop
bash ./scripts/ops/start-artifact-loop-hub.sh
```

Check the local hub:

```bash
bash ./scripts/ops/check-artifact-loop-hub.sh
```

Run scheduled briefs on Doug's host only:

```bash
bash ./scripts/ops/run-artifact-loop-briefs.sh
```

What these scripts guarantee:

- the hub binds only to `127.0.0.1`
- the port is checked before startup
- the PID and logs live under the hub data dir
- the brief runner uses the same data dir as the hub

Rollback:

- stop the PID in `~/.artifact-loop/team-hub/artifact-loop-hub.pid`
- leave the data dir intact

## Stage 1B — Tailscale Serve Exposure

Configure Tailscale Serve for the hub:

```bash
cd /Users/chadsimon/chad_bot_attempt/nemoclaw/artifact-loop
bash ./scripts/ops/configure-tailscale-artifact-loop-proxy.sh
```

Check the tailnet proxy:

```bash
bash ./scripts/ops/check-tailscale-artifact-loop-proxy.sh
```

The proxy is expected to:

- terminate HTTPS on tailnet port `4443`
- proxy to `http://127.0.0.1:4080`
- remain tailnet-only
- avoid Funnel/public exposure

Rollback:

```bash
tailscale serve --https=4443 off
```

This removes only the Artifact Loop endpoint on `:4443`. It does not touch the dashboard endpoint on the default HTTPS port.

## Stage 1C — Shared Hub Initialization

On Doug's host, bootstrap the shared coordination model once:

```bash
cd /Users/chadsimon/chad_bot_attempt/nemoclaw/artifact-loop

node bin/artifact-loop.js org bootstrap \
  --org-id org-core \
  --org-name "Core Org" \
  --org-timezone America/New_York \
  --team-id team-core \
  --team-name "Core Team" \
  --team-description "Shared coordination team" \
  --member-id lead-1 \
  --member-name "Lead" \
  --member-timezone America/New_York \
  --agent-id lead-agent-1 \
  --agent-label "Lead Agent" \
  --agent-connector lead-cli \
  --service-url https://nemoclaw.tailcc6c5f.ts.net:4443

node bin/artifact-loop.js team add-member team-core \
  --member worker-1 \
  --role worker \
  --by lead-1 \
  --name "Worker" \
  --timezone America/New_York \
  --worker-role worker \
  --service-url https://nemoclaw.tailcc6c5f.ts.net:4443

node bin/artifact-loop.js worker add-agent worker-1 \
  --id worker-agent-1 \
  --label "Worker Agent" \
  --connector remote \
  --service-url https://nemoclaw.tailcc6c5f.ts.net:4443
```

This creates the baseline team and actors used by the Stage 1 remote acceptance scenario.

## Stage 1D — Remote Shared Coordination Validation

On a teammate machine, set the shared hub URL:

```bash
export ARTIFACT_LOOP_SERVICE_URL=https://nemoclaw.tailcc6c5f.ts.net:4443
```

Run the tailnet-hosted acceptance scenario:

```bash
cd /Users/chadsimon/chad_bot_attempt/nemoclaw/artifact-loop
bash ./scripts/scenarios/tailscale_shared_coordination_v1.sh
```

What it validates:

- remote project/task reads through the shared hub
- task assignment and worker inbox acknowledgement
- remote worker progress written to the shared hub
- lead ping / task message visibility
- current brief readability from the same shared hub

Important boundary:

- the remote scenario reads the current brief only
- scheduled brief generation stays host-owned through `run-artifact-loop-briefs.sh`

Rollback on teammate machines:

```bash
unset ARTIFACT_LOOP_SERVICE_URL
```

## Stage 1 Acceptance Criteria

Stage 1 is complete when:

- Doug's host passes local hub checks
- the Tailscale Serve proxy passes tailnet checks
- one teammate machine can complete the shared coordination scenario through `https://nemoclaw.tailcc6c5f.ts.net:4443`
- Artifact Loop remains the source of truth for tasks, inbox, messages, and current briefs

## Stage 2 — Remote OpenClaw Gateway Profile

Deferred. This stage will add:

- reversible remote/local OpenClaw gateway profile scripts
- remote gateway connectivity checks
- one canonical remote runtime-backed action
- rollback back to local gateway mode

Stage 2 is not eligible to start until the Runtime Gate Boundary above is satisfied.

## Stage 3 — Combined Coordination + Runtime Acceptance

Deferred. This stage will add:

- one combined acceptance scenario using both the shared Artifact Loop hub and Doug's remote OpenClaw gateway
- guardrails proving coordination remains in Artifact Loop and runtime remains in OpenClaw

Stage 3 is not eligible to start until Stage 2 exists and the Runtime Gate Boundary above has already passed.

## Common Failure Cases

- Local hub health fails:
  - check `artifact-loop-hub.stdout.log` and `artifact-loop-hub.stderr.log`
- Tailnet health fails:
  - inspect `tailscale serve status --json`
  - confirm `:4443` still proxies to `127.0.0.1:4080`
- Remote scenario fails before project creation:
  - verify `org-core`, `team-core`, `lead-1`, `worker-1`, and `worker-agent-1` exist on the shared hub
- Current brief is readable but scheduled brief runs are stale:
  - run `bash ./scripts/ops/run-artifact-loop-briefs.sh` on Doug's host
