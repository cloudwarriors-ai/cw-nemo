# Artifact Loop Organization Stabilization Rollout

This note is the canonical operator-facing handoff for the current `artifact-loop` organization rollout work on branch `codex/session-source-visibility-20260319`.

It covers the newly implemented organization slices and the stabilization passes that should run before anyone treats the new surfaces as rollout-ready.

## What Shipped

The current branch adds the remaining organization product slices inside `artifact-loop`:

- Slice B: invite creation, pending memberships, invite claim, revoke, and claim-time first-agent activation
- Slice C: team projects, team summary, team brief, team brief schedules, and persisted team brief runs
- Slice D: CLI-only `org adopt-existing` dry-run, apply, and adoption status for wrapping legacy coordination data into the org model

The compatibility boundary stays intentionally narrow:

- direct `team add-member` still works for immediate active members
- post-claim `worker add-agent` still works
- team summary and team brief remain derived from project/task truth rather than a second team state machine
- adopt-existing remains CLI-only and local to the data dir being migrated

## Stabilization Entry Points

Run these from `/Users/chadsimon/chad_bot_attempt/nemoclaw/artifact-loop`:

```bash
npm run accept:shared-coordination
npm run scenario:org-surface-smoke
npm run review:lead-surfaces
```

What each one proves:

- `accept:shared-coordination`
  - the canonical shared lead/worker coordination loop still works
  - project/task assignment, inbox acknowledgement, worker progress, task messages, and project brief persistence remain intact
- `scenario:org-surface-smoke`
  - CLI invite creation succeeds
  - direct HTTP invite claim succeeds
  - CLI project/task coordination reaches `ready_for_review`
  - direct HTTP team projects, team summary, and team brief reads reflect the same truth
  - team brief scheduling and latest persisted run succeed
  - CLI `org adopt-existing` dry-run, apply, and `org adoption-status` succeed against an isolated seeded legacy fixture
- `review:lead-surfaces`
  - captures project and team lead-facing outputs into a review bundle
  - checks project summary, project workers, project brief, team summary, team brief, latest persisted brief runs, task messages, and inbox semantics for drift

## Core Operator Commands

Invite and claim:

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

Team reads and team brief schedule:

```bash
artifact-loop team projects team-core --by lead-1 --service-url http://127.0.0.1:4080
artifact-loop team summary team-core --by lead-1 --service-url http://127.0.0.1:4080
artifact-loop team brief team-core --by lead-1 --service-url http://127.0.0.1:4080
artifact-loop team schedule-brief team-core --owner-worker lead-1 --timezone America/New_York --delivery-hour 9 --service-url http://127.0.0.1:4080
artifact-loop team brief team-core --by lead-1 --latest-run --service-url http://127.0.0.1:4080
```

Adopt existing:

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

## Known Constraints

- Pending invite-only memberships are not active team members.
- Team summaries and briefs are derived-only read models.
- `org adopt-existing` is CLI-only; there is no mutating HTTP migration endpoint in this iteration.
- This pass does not implement Tailscale Stage 2 or Stage 3.

## Rollback And Cleanup

Local smoke and review runs create isolated temp roots under `/tmp/artifact-loop-*`.

If you ran a scenario or review with `KEEP_ALIVE=1`, stop the retained service PID before deleting the temp root. Otherwise the scripts clean up automatically on exit.

Rollback for this stabilization pass is bounded to:

- `artifact-loop/scripts/scenarios/org_surface_smoke_v1.sh`
- `artifact-loop/scripts/scenarios/lead_surface_review_v1.sh`
- `artifact-loop/scripts/scenarios/lib/shared-coordination-common.sh`
- `artifact-loop/package.json`
- `artifact-loop/README.md`
- `artifact-loop/docs/org-stabilization-rollout.md`
- `artifact-loop/docs/tailscale-rollout.md`
- `.agents/skills/artifact-loop-lead-surface-review/SKILL.md`

## Runtime Gate

Do not resume runtime-track implementation from this note alone.

Stage 2 and Stage 3 remain blocked until Doug completes Stage 1 on the target host and the shared tailnet URL is proven from another machine.

Runtime work becomes eligible only after all of the following are true:

1. Doug pulls branch `codex/session-source-visibility-20260319`.
2. Doug runs the Stage 1 host scripts successfully on his machine.
3. The tailnet URL passes `bash ./scripts/scenarios/tailscale_shared_coordination_v1.sh` from a teammate machine.

Until then:

- Artifact Loop remains the coordination truth
- OpenClaw remains the runtime plane
- Tailscale remains transport only
