# Artifact Loop

Artifact Loop is a file-backed coordination engine with a local CLI and a minimal shared HTTP service.

## Test Harness

The organization loop has a dedicated layered harness:

```bash
npm test
npm run test:harness
npm run accept:shared-coordination
npm run scenario:org-surface-smoke
npm run review:lead-surfaces
npm run scenario:shared-coordination
npm run scenario:tailscale-shared-coordination
```

- `npm test` includes the fast in-process harness coverage.
- `npm run test:harness` builds the package and runs both the fast harness suite and the higher-fidelity subprocess smoke suite against the built `artifact-loop` binary.
- `npm run accept:shared-coordination` runs the canonical shared lead/worker acceptance scenario and exits non-zero on any broken invariant.
- `npm run scenario:org-surface-smoke` runs the broader stabilization smoke that mixes CLI and direct HTTP validation for invite claim, team read models, scheduled team briefs, and CLI-only adopt-existing flow.
- `npm run review:lead-surfaces` reuses the shared-coordination scenario, captures the lead-facing project and team read surfaces, and asserts the semantics that are still stabilizing across inbox, messages, summaries, worker grouping, and brief output.
- `npm run scenario:shared-coordination` runs the canonical end-to-end lead/worker shared-coordination smoke scenario in isolated temp dirs and exits non-zero on any broken invariant.
- `npm run scenario:tailscale-shared-coordination` runs the shared-coordination path against an externally hosted Artifact Loop service URL and is intended for the Stage 1 Tailscale rollout.
- The harness lives under `src/__tests__/harness/` and verifies the lead/worker loop through CLI/API surfaces only, without any frontend or real model calls.

## Tailscale Rollout

Stage 1 of the Doug-hosted Tailscale rollout is documented in [docs/tailscale-rollout.md](/Users/chadsimon/chad_bot_attempt/nemoclaw/artifact-loop/docs/tailscale-rollout.md).

The Stage 1 operator surfaces are:

```bash
bash ./scripts/ops/start-artifact-loop-hub.sh
bash ./scripts/ops/check-artifact-loop-hub.sh
bash ./scripts/ops/configure-tailscale-artifact-loop-proxy.sh
bash ./scripts/ops/check-tailscale-artifact-loop-proxy.sh
bash ./scripts/ops/run-artifact-loop-briefs.sh
bash ./scripts/scenarios/tailscale_shared_coordination_v1.sh
```

This rollout keeps the planes separate:
- Artifact Loop is the coordination plane
- OpenClaw gateway remains the runtime plane
- Tailscale is transport only

## Stabilization Workflow

The canonical operator note for this branch lives in [docs/org-stabilization-rollout.md](/Users/chadsimon/chad_bot_attempt/nemoclaw/artifact-loop/docs/org-stabilization-rollout.md).

Use this sequence while the lead/worker operating model is still settling:

```bash
npm run accept:shared-coordination
npm run scenario:org-surface-smoke
npm run review:lead-surfaces
```

What each step means:
- `accept:shared-coordination` is the acceptance path for the real shared hub loop:
  - lead creates and assigns work
  - worker receives and acknowledges it
  - worker reports progress against shared truth
  - lead pings the worker agent
  - brief generation persists the resulting state
- `scenario:org-surface-smoke` is the mixed-surface stabilization pass:
  - bootstraps the org/team/lead locally
  - creates a worker invite over CLI and claims it over HTTP
  - reuses the shared project/task coordination loop
  - reads team projects, summary, and brief directly over HTTP
  - schedules and persists a team brief run
  - seeds an isolated legacy fixture and runs CLI-only adopt-existing dry-run/apply/status
- `review:lead-surfaces` is the lead-side stabilization pass:
  - it bootstraps the same acceptance scenario
  - captures the lead-facing project and team outputs into a review bundle
  - checks that `project summary`, `project workers`, `project brief`, `team summary`, `team brief`, `latest brief runs`, `task messages`, and `worker inbox` stay semantically aligned

Important nuance:
- if the scheduled brief is not yet due, both scenario paths force execution at the persisted `next_run_at`
- this is intentional and validates the persisted brief-run path without wall-clock waiting

The lead-surface review bundle includes:
- machine-readable JSON snapshots for project summary, worker grouping, current brief, latest brief run, messages, inbox, and schedule
- machine-readable JSON snapshots for team projects, team summary, current team brief, latest team brief run, and team brief schedule
- human-readable text renderings for the key lead-facing CLI surfaces
- a compact `review-summary.md` that records the semantic checks the script enforced

## Shared Coordination v1

Start the service:

```bash
npm run build
node bin/artifact-loop.js serve --host 127.0.0.1 --port 4080 --data-dir .artifact-loop
```

Create a task:

```bash
curl -sS -X POST http://127.0.0.1:4080/tasks \
  -H 'content-type: application/json' \
  --data @- <<'JSON'
{
  "id": "feat-http",
  "title": "HTTP service task",
  "description": "Verify shared coordination flow",
  "assignee_human_id": "chad",
  "status": "not_started",
  "acceptance_criteria": "Task receives passing evidence",
  "acceptance_signals": [
    {
      "id": "sig-test",
      "category": "test",
      "required": true,
      "success_condition": "tests pass",
      "pattern": "*.test.ts"
    }
  ],
  "depends_on": []
}
JSON
```

Assign a task:

```bash
curl -sS -X POST http://127.0.0.1:4080/tasks/feat-http/assignments \
  -H 'content-type: application/json' \
  --data '{"assignee_human_id":"chad","assignee_agent_id":"worker-agent-1","assigned_by":"lead"}'
```

Ingest an artifact:

```bash
curl -sS -X POST http://127.0.0.1:4080/artifacts/ingest \
  -H 'content-type: application/json' \
  --data @- <<'JSON'
{
  "artifact": {
    "id": "ra-test-1",
    "type": "test_result",
    "timestamp": "2026-03-19T12:00:00.000Z",
    "source": "worker-connector",
    "pointer": "memory://test-run",
    "summary": "Passing test evidence",
    "raw_payload": {
      "type": "test_result",
      "signal_id": "sig-test",
      "passed": true
    }
  },
  "context": {
    "primary_task_id": "feat-http",
    "session_id": "session-1",
    "worker_id": "worker-1",
    "worker_agent_id": "worker-agent-1",
    "context_source": "explicit_lock"
  }
}
JSON
```

Read state, history, and stats:

```bash
curl -sS http://127.0.0.1:4080/tasks/feat-http/state
curl -sS http://127.0.0.1:4080/tasks/feat-http/history
curl -sS http://127.0.0.1:4080/stats
```

## Remote Worker Connector v1

Point the existing worker-facing CLI at the shared service with either `--service-url` or `ARTIFACT_LOOP_SERVICE_URL`.

Run a worker command against the shared service:

```bash
artifact-loop emit test \
  --task feat-http \
  --signal-id sig-test \
  --passed \
  --worker worker-1 \
  --worker-agent agent-1 \
  --service-url http://127.0.0.1:4080
```

Use local session context with the remote service:

```bash
artifact-loop task use feat-http --data-dir .artifact-loop-worker
artifact-loop task status --service-url http://127.0.0.1:4080 --data-dir .artifact-loop-worker
artifact-loop run --next --service-url http://127.0.0.1:4080 --data-dir .artifact-loop-worker -- npm test
```

Use environment variables instead of flags:

```bash
export ARTIFACT_LOOP_SERVICE_URL=http://127.0.0.1:4080
export ARTIFACT_LOOP_WORKER_AGENT_ID=agent-1
artifact-loop emit git-diff --task feat-http --worker worker-1
artifact-loop stats
```

Notes:
- `task use` and `task unuse` remain local session-file operations in v1.
- Remote worker commands fail closed if the shared service is unavailable or rejects the request.
- Remote ingests persist `worker_id`, optional `worker_agent_id`, `context_source`, and `artifact_source`.

## Project Coordination v1

Bootstrap the org and first team before creating team-scoped projects:

```bash
curl -sS -X POST http://127.0.0.1:4080/org/bootstrap \
  -H 'content-type: application/json' \
  --data @- <<'JSON'
{
  "organization": {
    "id": "org-core",
    "name": "Core Org",
    "timezone": "America/New_York"
  },
  "initial_team": {
    "id": "team-core",
    "name": "Core Team",
    "description": "Primary coordination team"
  },
  "initial_member": {
    "id": "lead-1",
    "display_name": "Lead",
    "timezone": "America/New_York"
  },
  "initial_agent": {
    "id": "lead-agent-1",
    "label": "Lead Agent",
    "connector_type": "lead-cli"
  }
}
JSON
```

Create a project:

```bash
curl -sS -X POST http://127.0.0.1:4080/projects \
  -H 'content-type: application/json' \
  --data '{"id":"proj-core","team_id":"team-core","title":"Core Project","description":"Lead-readable coordination surface","owner_worker_id":"lead-1"}'
```

Link tasks to the project:

```bash
curl -sS -X POST http://127.0.0.1:4080/projects/proj-core/tasks \
  -H 'content-type: application/json' \
  --data '{"task_id":"feat-http"}'
```

Read project tasks, summary, and worker grouping:

```bash
curl -sS http://127.0.0.1:4080/projects/proj-core/tasks
curl -sS http://127.0.0.1:4080/projects/proj-core/summary
curl -sS http://127.0.0.1:4080/projects/proj-core/workers
curl -sS http://127.0.0.1:4080/projects/proj-core/brief
```

The project summary and brief are computed from current task state and derivation history, not separate project state machines. Existing local and remote worker evidence automatically contributes once tasks are linked to a project, and the brief includes a `by_worker` section grounded in persisted artifact provenance so leads can see who touched what.

## Organization Layer Slice A

Bootstrap the trusted single-org deployment and first admin:

```bash
artifact-loop org bootstrap \
  --org-id org-core \
  --org-name "Core Org" \
  --org-timezone America/New_York \
  --team-id team-core \
  --team-name "Core Team" \
  --team-description "Primary coordination team" \
  --member-id lead-1 \
  --member-name "Lead" \
  --member-timezone America/New_York \
  --agent-id lead-agent-1 \
  --agent-label "Lead Agent" \
  --agent-connector lead-cli \
  --service-url http://127.0.0.1:4080
```

Inspect the org and team, then add members directly with explicit roles:

```bash
artifact-loop org show --service-url http://127.0.0.1:4080
artifact-loop team list --service-url http://127.0.0.1:4080
artifact-loop team show team-core --service-url http://127.0.0.1:4080

artifact-loop team add-member team-core \
  --member worker-1 \
  --role worker \
  --name "Worker" \
  --timezone America/New_York \
  --by lead-1 \
  --service-url http://127.0.0.1:4080

artifact-loop team members team-core --service-url http://127.0.0.1:4080

artifact-loop worker add-agent worker-1 \
  --id worker-agent-1 \
  --label "Worker Agent" \
  --connector remote \
  --service-url http://127.0.0.1:4080
```

Invite-based onboarding is also available for pending members:

```bash
artifact-loop team invite team-core \
  --member worker-claim \
  --role worker \
  --name "Claim Worker" \
  --timezone America/New_York \
  --by lead-1 \
  --service-url http://127.0.0.1:4080

artifact-loop invite claim \
  --token <claim-token> \
  --agent-id worker-claim-agent \
  --agent-label "Claim Agent" \
  --agent-connector remote \
  --service-url http://127.0.0.1:4080
```

In Slice A, canonical authority comes from team membership:
- `admin` can bootstrap the org, create teams, and add members
- `lead` can create team-scoped projects, approve task drafts, assign same-team workers, and own brief schedules
- `worker` can receive assignments, report progress, and participate in same-team task messages

Every new project must belong to exactly one team, and assignments/messages must stay inside that team.

## Organization Loop v1

Create a team-scoped project definition, generate draft tasks, and approve them:

```bash
artifact-loop project create \
  --id proj-core \
  --team team-core \
  --title "Core Project" \
  --description "Organization loop" \
  --owner-worker lead-1 \
  --goal "Ship the organization loop" \
  --scope "lead flow" \
  --deliverable "Lead workflow" \
  --constraint "No auth" \
  --definition-of-done "Lead can define, assign, and monitor work" \
  --service-url http://127.0.0.1:4080

artifact-loop project generate-drafts proj-core \
  --agent lead-agent-1 \
  --service-url http://127.0.0.1:4080

artifact-loop project draft-sets proj-core --service-url http://127.0.0.1:4080
artifact-loop project approve-drafts proj-core <draft-set-id> --by lead-1 --service-url http://127.0.0.1:4080
```

Assign tasks, read worker inbox, send task-scoped pings, and schedule daily briefs:

```bash
artifact-loop task assign <task-id> --worker worker-1 --agent worker-agent-1 --by lead-1 --service-url http://127.0.0.1:4080
artifact-loop worker inbox --agent worker-agent-1 --service-url http://127.0.0.1:4080
artifact-loop task ping <task-id> --from-worker lead-1 --from-agent lead-agent-1 --to-worker worker-1 --to-agent worker-agent-1 --body "Please start this task." --service-url http://127.0.0.1:4080
artifact-loop project schedule-brief proj-core --owner-worker lead-1 --timezone America/New_York --delivery-hour 9 --service-url http://127.0.0.1:4080
artifact-loop run-scheduled-briefs --data-dir .artifact-loop
```

The same loop is CLI-first for both humans and LLM operators. Core read paths are available without a frontend, with human output by default and structured output via `--json`:

```bash
artifact-loop project list --service-url http://127.0.0.1:4080
artifact-loop project show proj-core --service-url http://127.0.0.1:4080
artifact-loop project tasks proj-core --service-url http://127.0.0.1:4080
artifact-loop project summary proj-core --service-url http://127.0.0.1:4080
artifact-loop project workers proj-core --service-url http://127.0.0.1:4080
artifact-loop project brief-schedule proj-core --service-url http://127.0.0.1:4080

artifact-loop worker list --service-url http://127.0.0.1:4080
artifact-loop worker show worker-1 --service-url http://127.0.0.1:4080
artifact-loop worker agents worker-1 --service-url http://127.0.0.1:4080
artifact-loop worker inbox --agent worker-agent-1 --service-url http://127.0.0.1:4080
artifact-loop worker inbox-ack <inbox-item-id> --service-url http://127.0.0.1:4080

artifact-loop task messages <task-id> --service-url http://127.0.0.1:4080
artifact-loop task message-ack <message-id> --service-url http://127.0.0.1:4080
artifact-loop project summary proj-core --json --service-url http://127.0.0.1:4080
```

## Team Briefs

Team-level read models are derived from existing project and task truth. Leads and admins can read the same project-level signals rolled up across the team:

```bash
artifact-loop team projects team-core --by lead-1 --service-url http://127.0.0.1:4080
artifact-loop team summary team-core --by lead-1 --service-url http://127.0.0.1:4080
artifact-loop team brief team-core --by lead-1 --service-url http://127.0.0.1:4080
artifact-loop team schedule-brief team-core --owner-worker lead-1 --timezone America/New_York --delivery-hour 9 --service-url http://127.0.0.1:4080
artifact-loop team brief-schedule team-core --by lead-1 --service-url http://127.0.0.1:4080
artifact-loop run-scheduled-briefs --data-dir .artifact-loop
artifact-loop team brief team-core --by lead-1 --latest-run --service-url http://127.0.0.1:4080
```

Team summaries and briefs stay derived-only:
- they do not introduce a second team state machine
- they aggregate existing project summaries, task state, derivation movement, workload, and brief history
- pending invite-only memberships are not treated as active team members

## Adopt Existing

Legacy file-backed coordination data can be wrapped into the organization model with a CLI-only migration path:

```bash
artifact-loop org adopt-existing \
  --org-id org-legacy \
  --org-name "Legacy Org" \
  --org-timezone America/New_York \
  --team-id team-legacy \
  --team-name "Legacy Team" \
  --team-description "Default adopted team" \
  --data-dir .artifact-loop

artifact-loop org adopt-existing \
  --org-id org-legacy \
  --org-name "Legacy Org" \
  --org-timezone America/New_York \
  --team-id team-legacy \
  --team-name "Legacy Team" \
  --team-description "Default adopted team" \
  --apply \
  --data-dir .artifact-loop

artifact-loop org adoption-status --data-dir .artifact-loop
```

The adoption flow is fail-closed:
- it blocks if org/team state already exists in a conflicting way
- it backfills existing workers into the default team as active memberships
- it assigns `team_id` onto existing projects
- it disables invalid legacy brief schedules and records that in the adoption report
