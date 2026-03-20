# Decision: CLAUDE.md Restructure to State Machine Model

**Date:** 2026-01-11
**Status:** Approved
**Council:** Adversarial Council (Alex Chen, Sam Rivera, Jordan Taylor)

## Context

The original CLAUDE.md used a step-based workflow that didn't clearly define task states or handle external service rate limits effectively. After hitting Simli rate limits during avatar integration, a restructure was proposed.

## Decision

Adopt a state machine model with:
1. Explicit task states (DRAFT → IMPLEMENTED → READY_FOR_APPROVAL → APPROVED)
2. Hard limits on external service calls per session
3. Selective council invocation (skip for trivial changes)
4. Issue severity classification (BLOCKER/MAJOR/MINOR/NIT)
5. Clear SMS notification rules (mandatory vs forbidden)
6. Decision autonomy framework

## Alternatives Considered

1. **Raw YAML format** - Rejected: Claude follows prose better than structured YAML
2. **No hard limits** - Rejected: Rate limits are too costly to hit repeatedly
3. **Council for everything** - Rejected: Adds overhead for trivial changes

## Council Findings

### Adopted
- State machine with 6 states
- External service limits with health check exception
- Council skip/required conditions
- Issue severity classification
- Artifact requirements

### Modified
- Keep markdown format (not YAML)
- Add health check exception (1 call allowed)
- Track limits in persistent file
- MAJOR issues "should fix" not "must fix"

### Rejected
- Raw YAML format
- Overly rigid limits without escape hatch

## Consequences

### Positive
- Clear task state at any point
- Prevents rate limit disasters
- Reduces unnecessary council overhead
- Documents decisions for future context

### Negative
- More complex mental model
- Requires tracking file management
- May slow down rapid iteration

## Implementation

- Updated CLAUDE.md with new structure
- Created `.claude/session_limits.json` for tracking
- Created `docs/decisions/` for architectural decisions
