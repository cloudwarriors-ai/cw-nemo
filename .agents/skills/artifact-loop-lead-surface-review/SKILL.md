---
name: artifact-loop-lead-surface-review
description: Run the Artifact Loop lead-surface stabilization review when the user wants to validate or inspect the lead-facing project and team summaries, worker grouping, briefs, inbox, and task-message semantics after the shared coordination loop.
metadata:
  short-description: Run Artifact Loop lead-surface review flow
---

# Artifact Loop Lead Surface Review

Use this skill when the user wants to validate that the lead-facing read surfaces remain semantically aligned while the coordination model is still settling.

Run the stabilization review script:

```bash
cd /Users/chadsimon/chad_bot_attempt/nemoclaw/artifact-loop
bash ./scripts/scenarios/lead_surface_review_v1.sh
```

What the script does:
- bootstraps the canonical shared-coordination acceptance scenario in isolated temp dirs
- keeps that runtime alive long enough to capture lead-facing outputs
- records JSON and human-readable snapshots for:
  - project summary
  - project worker grouping
  - current brief
  - latest persisted brief run
  - task messages
  - worker inbox
- team projects
- team summary
- current team brief
- latest persisted team brief run
- team brief schedule
- checks that both the project and team lead surfaces stay semantically aligned
- writes a compact `review-summary.md` into the review bundle

Important nuance:
- if the brief schedule is not yet wall-clock due, the bootstrap scenario forces execution at the persisted `next_run_at`
- this is intentional and validates the persisted brief-run path without waiting for real time

Operator notes:
- the script exits non-zero on any semantic drift it detects
- prefer this when the goal is to validate lead-facing semantics, not only the raw shared-coordination acceptance path
- after running, report the review bundle path and any failing invariant to the user
