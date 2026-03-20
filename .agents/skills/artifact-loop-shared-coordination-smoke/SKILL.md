---
name: artifact-loop-shared-coordination-smoke
description: Run the canonical Artifact Loop shared-coordination smoke scenario when the user asks to validate the lead/worker org loop, shared coordination, inbox/message flow, or brief generation end to end from CLI/API surfaces.
metadata:
  short-description: Run Artifact Loop shared-coordination smoke flow
---

# Artifact Loop Shared Coordination Smoke

Use this skill when the user wants to validate the real lead/worker coordination loop for `artifact-loop` without relying on a frontend.

Run the canonical scenario script:

```bash
cd /Users/chadsimon/chad_bot_attempt/nemoclaw/artifact-loop
bash ./scripts/scenarios/shared_coordination_v1.sh
```

What the script validates:
- shared service startup in isolated temp dirs
- lead and worker identity registration
- project creation, draft generation, and draft approval
- assignment delivery to worker inbox
- worker inbox acknowledgement
- worker progress reporting through the shared service
- lead ping/message visibility and acknowledgement
- project summary and worker summary updates
- scheduled brief persistence and latest brief readback

Important nuance:
- if the brief schedule is not yet wall-clock due, the script forces execution at the persisted `next_run_at`
- this is intentional and validates the persisted brief-run path without waiting for real time

Operator notes:
- the script exits non-zero on any broken invariant
- prefer the script’s structured checks over ad hoc manual commands when the goal is smoke validation
- after running, report the PASS/FAIL summary and any failing invariant to the user
