# Artifact Loop: Short Real-Usage Trial and Friction Review

Trial window:
- 3 short local work sessions on March 19, 2026
- Current surface only: `task use`, `task status`, `task history`, `run`, `emit git-diff`, `stats`

Observed data sources:
- `baseline-stats.json`
- `final-stats.json`
- `trial-data/usage/events.jsonl`
- `session-log.md`

## What was actually used
- Baseline started empty: zero command-resolution events, zero artifacts, zero overrides.
- Final stats showed:
  - `task_use`: `set=1`, `change=1`, `clear=0`
  - command resolution: `session_default=10`, `explicit_lock=1`, `explicit_over_session_override=1`
  - artifacts: `command_result=1`, `test_result=1`, `git_diff_summary=1`
  - evidence buckets: `automatic_any=1`, `none=1`
- The actual working loop centered on one task:
  - set current task once
  - run `npm run check`
  - run `npm test`
  - inspect status/history
  - emit one git diff summary
- The second task was used mainly as a review/read context, not as an evidence-producing task.

## What was awkward or avoided
- The most repeated friction was signal targeting for `run`.
  - I had to remember `sig-check` and `sig-tests` from task setup rather than discovering them from the normal read surface.
  - `task status` and `task history` did not help me recover the runnable signal IDs.
- I avoided using `emit note` for review prose.
  - The CLI felt good for evidence and state reads.
  - It did not feel natural for lightweight narrative capture during the review itself.
- `emit git-diff` was useful, but it remained an explicit after-the-fact step rather than an ambient capture.

## What caused overrides or manual cleanup
- No task override events occurred.
- No manual cleanup was required to repair bad state.
- One explicit-over-session read occurred while the review task was active.
  - This was used to inspect `validate-real-work-capture` while `review-trial-findings` was the current task.
  - It was navigation, not state repair.

## What already worked well enough
- Session-default task context worked well enough.
- `run` plus `task status`/`task history` produced a trustworthy local loop for command/test evidence.
- `emit git-diff` stayed non-derivational and did not create state confusion.
- No change is proposed to those behaviors from this review.

## Recommended single follow-up
- Surface acceptance signal IDs and categories directly in the human `task status` output for the current task.

## Why that one wins
- It removes the only repeated friction that showed up in the common workflow: remembering the right `signal_id` before every meaningful `run`.
- It reduces the need to leave the normal CLI read surface or rely on memory.
- It increases trust and ease-of-use without widening architecture, adding a daemon, or inventing a new subsystem.
- It beats other plausible next steps right now because the session-default model, stats surface, and git evidence path already worked well enough during the trial; the recurring pain was signal discoverability, not architecture.
