# Artifact Loop Trial Log

Baseline:
- Trial data dir started empty.
- No preexisting trial tasks, artifacts, derivations, or usage events were present in this track.
- Baseline `stats --json` showed zero command-resolution and artifact counts.

## Session 1
- Task worked on: `validate-real-work-capture`
- Commands actually used:
  - `artifact-loop task use validate-real-work-capture`
  - `artifact-loop run --kind command --signal-id sig-check -- npm run check`
  - `artifact-loop task status`
- Felt smooth:
  - `task use` plus session-default targeting removed the need to repeat `--task`.
  - The `run` output made the resulting state transition obvious.
- Felt annoying:
  - I had to remember the correct `signal_id` up front; the read surface did not help me recover it.
- Avoided:
  - No manual note or override use in this session.

## Session 2
- Task worked on: `validate-real-work-capture`
- Commands actually used:
  - `artifact-loop run --signal-id sig-tests -- npm test`
  - `artifact-loop task status`
  - `artifact-loop task history`
  - `artifact-loop emit git-diff`
- Felt smooth:
  - `run` moved the task to `ready_for_review` cleanly.
  - `task history` confirmed the derivation path without ambiguity.
  - `emit git-diff` added worktree evidence without changing canonical state.
- Felt annoying:
  - `emit git-diff` still required a manual “remember to capture this” step after the work was already done.
  - The git summary was truthful but broad on a dirty working tree.
- Avoided:
  - I did not use `emit note` for trial narrative or review context because that would have felt like extra clerical work.

## Session 3
- Task worked on: `review-trial-findings`
- Commands actually used:
  - `artifact-loop task use review-trial-findings`
  - `artifact-loop task status validate-real-work-capture`
  - `artifact-loop task status`
- Felt smooth:
  - Explicit task reads while another task was active were clear and predictable.
  - Session-default status reads remained easy to trust.
- Felt annoying:
  - The validation task was easy to locate, but the CLI still did not surface the runnable signal IDs needed for future `run` calls.
- Avoided:
  - No override or manual note was needed.
