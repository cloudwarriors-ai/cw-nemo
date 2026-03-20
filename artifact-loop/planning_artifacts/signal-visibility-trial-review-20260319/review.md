# Artifact Loop: Signal Visibility Trial Review

Trial window:
- 3 short local work sessions on March 19, 2026
- Current surface used: `task use`, `task status`, `task history`, `run`, `emit git-diff`, `stats`

Observed data sources:
- `baseline-stats.json`
- `final-stats.json`
- `trial-data/usage/events.jsonl`
- `session-log.md`

Question under review:
- Did signal visibility in `task status` materially reduce command friction in practice?

Answer:
- Yes. Signal lookup friction was removed in the core `run` loop.
- The remaining friction is mostly typing burden, not signal discovery.

## What was actually used
- Baseline started empty: no task-use events, no command-resolution events, and no artifacts.
- Final stats showed:
  - `task_use`: `set=1`, `change=1`, `clear=0`
  - command resolution: `session_default=7`, `explicit_lock=2`, `explicit_over_session_override=2`
  - artifacts: `command_result=1`, `test_result=1`, `git_diff_summary=1`
  - evidence buckets: `automatic_any=1`, `none=1`
- The actual working loop was:
  - set the current task once
  - read `task status`
  - run the hinted command signal
  - read `task status` again
  - run the hinted test signal
  - emit one git diff summary
  - switch to the review task and inspect the completed task explicitly

## What was awkward or avoided
- Signal lookup itself was no longer awkward.
  - `task status` showed both signal ids and the next likely step.
  - I did not need to leave the CLI or inspect task JSON to know what to run.
- The remaining repeated friction was typing.
  - I still had to copy or retype `--signal-id sig-check` and `--signal-id sig-tests` even after status had already identified the next signal.
- I avoided manual notes and overrides completely.

## What caused overrides or manual cleanup
- No overrides occurred.
- No manual cleanup was required to repair task state.
- The two explicit-over-session reads happened during review:
  - `task status validate-signal-visibility`
  - `task history validate-signal-visibility`
- Those were review/navigation actions, not evidence of broken task targeting.

## What already worked well enough
- Signal visibility in `task status` worked well enough to remove lookup friction in the normal `run` loop.
- The next-step hint was used directly and advanced correctly from the command signal to the test signal.
- Session-default task context remained the dominant path.
- `emit git-diff` stayed non-derivational and did not introduce state confusion.
- No change is proposed to those behaviors from this review.

## Recommended single follow-up
- Add a minimal `artifact-loop run --next -- <command>` mode that binds to the first unmet required signal for the current task.

## Why that one wins
- The positive trial result means the remaining friction is no longer “what signal should I use?” but “why do I still have to type the signaled id manually?”
- `run --next` would remove repeated keystroke burden in the common path without adding new signal semantics, inference, or background systems.
- It would build directly on the now-proven status visibility model rather than widening architecture.
- It beats other plausible improvements right now because current-task visibility, signal discoverability, and derivation trust all held up during the trial; the residual annoyance is command construction overhead.
