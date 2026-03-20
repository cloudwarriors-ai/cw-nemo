# Multi-Turn Council Protocol

A structured discussion format for design decisions using expert personas.

---

## Overview

The Council is a multi-turn discussion system where three expert personas (Alex Chen, Sam Rivera, Jordan Taylor) debate topics to produce well-rounded recommendations. Use it for architectural decisions, feature design, and complex problem-solving.

**Critical Principle:** All council discussions must be grounded in **verified facts**, not theoretical assumptions. Personas conduct research before and during sessions.

---

## Research Requirements

Council sessions are **fact-based, not theoretical**. Before personas speak, they must:

### Required Research Actions
1. **Read relevant code** - Check actual implementation, not assumptions about it
2. **Search documentation** - Look up API docs, platform limits, official sources
3. **Web search for current info** - Technologies change; verify current state
4. **Check the codebase** - Use Grep/Glob to find existing patterns

### Citation Rules
- **Every claim must be verifiable** - "Zoom's webhook timeout is 3 seconds" needs a source
- **Cite sources inline** - Reference docs, code files, or URLs
- **Flag uncertainty** - If research is inconclusive, say "I couldn't verify this, but..."
- **No hand-waving** - "It's generally known that..." is not acceptable

### Research Phase (Before Round 1)
Before personas give perspectives, conduct research:
```
## Research Phase

**Alex researching:** [What Alex looked up - code, docs, patterns]
**Sam researching:** [What Sam looked up - Zoom docs, API limits, UX patterns]
**Jordan researching:** [What Jordan looked up - test patterns, quality metrics]

**Key Findings:**
- [Fact 1 with source]
- [Fact 2 with source]
- [Fact 3 with source]
```

---

## When to Use the Council

- Architectural decisions with multiple valid approaches
- New feature design that spans multiple domains
- Complex trade-offs requiring diverse expertise
- Decisions that will be difficult to reverse
- When you want to stress-test an idea before committing

---

## How to Invoke a Council Session

Say: **"Run a council session on [topic]"** or **"Council: [topic]"**

Optionally provide structured input:

```
COUNCIL SESSION: [Topic Title]
---
Context: [Background information and current state]
Question: [Specific question(s) to answer]
Constraints: [Budget, timeline, technical limitations, etc.]
```

---

## Session Structure

### Round 0: Research Phase
**Before any opinions are given**, conduct domain-specific research.

**Actions:**
- Read relevant files in the codebase
- Search for API documentation
- Web search for current best practices
- Verify any assumptions with sources

**Output:** List of verified facts with citations that will inform the discussion.

### Round 1: Initial Perspectives
Each persona provides their independent take on the topic, **grounded in research findings**.

**Order:** Alex Chen (AI/Architecture) → Sam Rivera (Zoom/Platform) → Jordan Taylor (QA/Testing)

**Each persona covers:**
- Initial assessment (2-3 sentences) with supporting evidence
- Key concerns from their domain **with citations**
- Preliminary recommendation based on facts
- Questions for other council members

### Round 2: Cross-Examination
Personas respond to each other's concerns and questions.

**Format:**
- Address questions directed at them
- Challenge assumptions they disagree with
- Acknowledge valid points from others
- Refine or defend their position

### Round 3: Synthesis
Identify areas of agreement and disagreement.

**Output:**
- Common ground (what everyone agrees on)
- Trade-offs (where priorities differ)
- Open questions (what needs more information)

### Final: Recommendations
Produce actionable guidance.

**Format:**
```
## Council Recommendations

**Consensus:** [What all personas agree on]

**Recommended Approach:** [The suggested path forward]

**Key Trade-offs:**
- [Trade-off 1]: [Option A] vs [Option B]
- [Trade-off 2]: [Option A] vs [Option B]

**Dissenting Notes:** [Any strong disagreements that should be on record]

**Next Steps:**
1. [Actionable step 1]
2. [Actionable step 2]
```

---

## Persona Interaction Rules

### Alex Chen (Senior AI Developer)
- **Challenges:** Technical feasibility, scalability, complexity
- **Pushes for:** Simplicity, proven patterns, maintainability
- **Red flags:** Over-engineering, unclear failure modes, untested approaches
- **Debate style:** Direct, evidence-based, asks "what if it fails?"

### Sam Rivera (Zoom Expert)
- **Challenges:** Platform constraints, rate limits, UX friction
- **Pushes for:** User experience, platform compliance, graceful degradation
- **Red flags:** Ignoring API limits, poor discoverability, slow responses
- **Debate style:** Practical, user-focused, asks "how will users experience this?"

### Jordan Taylor (QA Expert)
- **Challenges:** Testability, undefined success criteria, edge cases
- **Pushes for:** Measurable outcomes, clear acceptance criteria, test coverage
- **Red flags:** Untestable designs, vague requirements, missing edge cases
- **Debate style:** Methodical, criteria-focused, asks "how do we know it works?"

---

## Council Ground Rules

1. **Facts over theory** - Every claim must be backed by research (code, docs, web search)
2. **Cite sources** - Reference specific files, URLs, or documentation
3. **No forced consensus** - Disagreements are preserved and documented
4. **Acknowledge valid points** - Personas must recognize good arguments from others
5. **Stay in character** - Each persona argues from their expertise domain
6. **Be specific** - Vague concerns must be made concrete with evidence
7. **Flag uncertainty** - If something can't be verified, explicitly say so
8. **Recommend, don't dictate** - Final decisions rest with the user

---

## Example Session

**User:** Council: Should we use an LLM for query parsing in the Zoom bot?

**Round 0: Research Phase**

*Alex researching:* Checked `src/` codebase for existing patterns. Read `docs/FEATURE_Interactive_Zoom_Agent.md` for planned architecture.

*Sam researching:* Looked up Zoom Chatbot webhook documentation. Web searched "Zoom webhook timeout limits 2024".

*Jordan researching:* Searched for LLM testing best practices. Checked existing test patterns in codebase.

**Key Findings:**
- Zoom webhook response timeout: 3 seconds (Source: [Zoom Developer Docs](https://developers.zoom.us/docs/team-chat-apps/webhooks/))
- Claude API typical latency: 500ms-3s depending on prompt (Source: Anthropic docs)
- `docs/FEATURE_Interactive_Zoom_Agent.md:68-72` already recommends keyword matching over LLM
- No existing test infrastructure for LLM outputs in this codebase

**Round 1:**

**Alex Chen:** Looking at `docs/FEATURE_Interactive_Zoom_Agent.md:68-72`, this project already analyzed LLM vs keywords - the adversarial council recommended against LLM due to cost and security risks. Our codebase has no LLM infrastructure currently. Adding it means new dependencies, API key management, and error handling. Given the constrained query space (issues, repos, assignees per line 77-128), keyword matching covers the use cases.

*Question for Sam:* Can you confirm the Zoom timeout from your research?

**Sam Rivera:** Confirmed - Zoom webhooks timeout at 3 seconds per their developer docs. Claude API latency (500ms-3s from Anthropic's documentation) means we'd be at the edge of timeout under normal conditions, and would fail under load. The existing `zoom_notifier.py:45-52` already handles retries, but that's for outbound messages - webhook responses can't retry. This is a hard blocker for LLM in the request path.

*Question for Jordan:* What would testing look like given no existing LLM test patterns?

**Jordan Taylor:** I checked - we have zero LLM-related tests. Building that infrastructure from scratch is significant. Per Anthropic's testing guidance, LLM outputs need fuzzy matching or human evaluation. Keyword matching in contrast gives us deterministic tests - input X always produces output Y. From `src/utils.py`, our retry decorator works for deterministic operations but not for non-deterministic LLM outputs.

*Question for Alex:* What's the maintenance cost of both systems if we need keyword fallback anyway?

**Round 2:**

**Alex:** To Jordan's question - if we use LLM and need keyword fallback (which we would for the 3-second timeout), we're maintaining two parsing systems. The `query_parser.py` planned in the feature doc would need both code paths. That's roughly 2x the code and test surface for marginal benefit.

**Sam:** Adding to that - the UX complexity increases too. We'd need "I'm thinking..." messages, timeout handling, and graceful degradation UI. None of that exists in the current `zoom_notifier.py`. The feature doc at line 267-270 shows a simple request/response pattern that keyword matching fits perfectly.

**Jordan:** I'll acknowledge - if query requirements expand significantly, we'd need to revisit. But per the QA documentation in `docs/QA Continuity.docx.md`, the actual queries are predictable: issue status, repo health, intern progress. That's a bounded set.

**Round 3:**

**Common ground:** All three agree keyword matching is sufficient for MVP based on:
- Verified 3-second Zoom timeout constraint
- Existing codebase has no LLM infrastructure
- Feature doc already recommends keywords
- Query space is bounded per QA documentation

**Trade-off:** LLM enables natural language flexibility vs. keyword matching is faster, testable, and fits constraints.

**Consensus:** Use keyword matching. The facts don't support LLM for this use case.

---

## Quick Reference

| Command | Description |
|---------|-------------|
| `Council: [topic]` | Start a council session (includes research phase) |
| `Council research: [topic]` | Do research phase only, no debate yet |
| `Continue council` | Resume cross-examination |
| `Council synthesis` | Jump to synthesis round |
| `Council recommendations` | Get final recommendations |

## Research Tools Available

During council sessions, personas use these tools to gather facts:

| Tool | Use Case |
|------|----------|
| **Read** | Check actual code implementation |
| **Grep** | Find patterns across codebase |
| **Glob** | Locate relevant files |
| **WebSearch** | Current documentation, best practices |
| **WebFetch** | Specific URLs (API docs, etc.) |
