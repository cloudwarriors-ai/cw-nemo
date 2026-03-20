# Signal Visibility Trial Log

Baseline:
- Trial data dir started empty.
- Baseline `artifact-loop stats --json` showed zero task-use events, zero command-resolution events, and zero artifacts.

## Session 1
- Task worked on: `validate-signal-visibility`
- Commands actually used:
  - `artifact-loop task use validate-signal-visibility`
  - `artifact-loop task status`
  - `artifact-loop run --kind command --signal-id sig-check -- npm run check`
  - `artifact-loop task status`
- Felt smooth:
  - `task status` exposed `sig-check` directly, so there was no need to remember or rediscover the signal id elsewhere.
  - The next-step hint was immediately usable.
- Felt annoying:
  - I still had to type the full `--signal-id sig-check` string even though status had already chosen the next signal for me.
- Avoided:
  - No external signal lookup and no manual note/override use.

## Session 2
- Task worked on: `validate-signal-visibility`
- Commands actually used:
  - `artifact-loop run --signal-id sig-tests -- npm test`
  - `artifact-loop emit git-diff`
  - `artifact-loop task status`
- Felt smooth:
  - The status hint had advanced to `sig-tests`, and I used it directly.
  - After both required signals were satisfied, `task status` stopped showing a next-step hint, which matched expectations.
  - `emit git-diff` still fit the loop without polluting state.
- Felt annoying:
  - The hint reduced lookup friction but not typing friction.
  - `emit git-diff` remained an explicit extra step after the main work loop.
- Avoided:
  - No manual note or override use.

## Session 3
- Task worked on: `review-signal-trial`
- Commands actually used:
  - `artifact-loop task use review-signal-trial`
  - `artifact-loop task status`
  - `artifact-loop task status validate-signal-visibility`
  - `artifact-loop task history validate-signal-visibility`
- Felt smooth:
  - Session-default remained the normal read path.
  - Explicit reads of the completed validation task felt like review/navigation, not a workaround.
- Felt annoying:
  - The review task had an optional signal row but no next-step hint, which was fine, but it did not need any further status richness.
- Avoided:
  - No override use and no need to inspect task definitions outside the CLI.
