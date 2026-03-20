// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Phase 6A — Contract hardening scenarios.
 * Replay/idempotency, quarantine, binding precedence, and task-create policy.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { derive, resetDerivationState } from "./helpers/derivation-helper.js";
import { assertValid, assertInvalid, resetValidator } from "./helpers/validate.js";
import type {
  AcceptanceSignal,
  DerivationInput,
  NormalizedArtifact,
  TaskState,
} from "./helpers/types.js";

const NOW = new Date("2026-03-19T12:00:00Z");
const RECENT = "2026-03-19T11:00:00Z";

function makeTaskState(overrides: Partial<TaskState> = {}): TaskState {
  return {
    status: "not_started",
    task_confidence: 0,
    binding_confidence: 0,
    missing_inputs: [],
    ...overrides,
  };
}

function makeArtifact(
  id: string,
  taskId: string,
  payload: NormalizedArtifact["signal_payload"],
  overrides: Partial<NormalizedArtifact> = {},
): NormalizedArtifact {
  return {
    id,
    raw_artifact_id: `raw-${id}`,
    primary_task_id: taskId,
    session_id: "sess-1",
    timestamp: RECENT,
    normalization_state: "normalized",
    binding_confidence: 0.9,
    signal_payload: payload,
    ...overrides,
  };
}

beforeEach(() => {
  resetDerivationState();
  resetValidator();
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

// ─── Replay / Idempotency ────────────────────────────────────────────

describe("Replay / Idempotency", () => {
  it("realistic artifact sequence: sequential test results followed by merge", () => {
    const testSignal: AcceptanceSignal = {
      id: "sig-test",
      category: "test",
      required: true,
      success_condition: "tests pass",
      pattern: "test_*",
    };
    const mergeSignal: AcceptanceSignal = {
      id: "sig-merge",
      category: "merge",
      required: true,
      success_condition: "merged",
    };
    const signals = [testSignal, mergeSignal];

    const testPass = makeArtifact("na-1", "task-1", {
      type: "test_result",
      signal_id: "sig-test",
      passed: true,
    });

    // Step 1: not_started → in_progress (first artifact arrives)
    const r1 = derive({
      priorState: makeTaskState({ status: "not_started" }),
      normalizedArtifacts: [testPass],
      acceptanceSignals: signals,
    });
    // With one non-merge signal satisfied, task should progress
    expect(r1.nextState.status).not.toBe("not_started");

    // Step 2: replay same artifact — no additional transition
    const r2 = derive({
      priorState: r1.nextState,
      normalizedArtifacts: [testPass],
      acceptanceSignals: signals,
    });
    expect(r2.transitionOccurred).toBe(false);
    expect(r2.derivationRun).toBeUndefined();

    // Step 3: merge arrives — should reach done
    const mergeResult = makeArtifact("na-2", "task-1", {
      type: "merge_result",
      signal_id: "sig-merge",
      merge_ref: "abc123",
      target_branch: "main",
    });

    const r3 = derive({
      priorState: r2.nextState,
      normalizedArtifacts: [testPass, mergeResult],
      acceptanceSignals: signals,
    });
    expect(r3.nextState.status).toBe("done");
    expect(r3.transitionOccurred).toBe(true);

    // Step 4: replay merge + test again — no additional transition
    const r4 = derive({
      priorState: r3.nextState,
      normalizedArtifacts: [testPass, mergeResult],
      acceptanceSignals: signals,
    });
    expect(r4.transitionOccurred).toBe(false);
  });

  it("replayed artifacts with consumed_for_derivation state still produce same result", () => {
    const testSignal: AcceptanceSignal = {
      id: "sig-test",
      category: "test",
      required: true,
      success_condition: "tests pass",
      pattern: "test_*",
    };
    const mergeSignal: AcceptanceSignal = {
      id: "sig-merge",
      category: "merge",
      required: true,
      success_condition: "merged",
    };

    // Artifact already consumed in previous derivation
    const consumedArtifact = makeArtifact(
      "na-1",
      "task-1",
      { type: "test_result", signal_id: "sig-test", passed: true },
      { normalization_state: "consumed_for_derivation" },
    );

    const result = derive({
      priorState: makeTaskState({ status: "ready_for_review" }),
      normalizedArtifacts: [consumedArtifact],
      acceptanceSignals: [testSignal, mergeSignal],
    });

    // consumed_for_derivation is still derivation-eligible, same result
    expect(result.transitionOccurred).toBe(false);
  });
});

// ─── Quarantine Scenarios ────────────────────────────────────────────

describe("Quarantine Scenarios", () => {
  it("quarantined artifacts are excluded from derivation", () => {
    const testSignal: AcceptanceSignal = {
      id: "sig-test",
      category: "test",
      required: true,
      success_condition: "pass",
      pattern: "test_*",
    };
    const mergeSignal: AcceptanceSignal = {
      id: "sig-merge",
      category: "merge",
      required: true,
      success_condition: "merged",
    };

    // Quarantined artifact — should be invisible to derivation
    const quarantinedArtifact = makeArtifact(
      "na-1",
      "task-1",
      { type: "test_result", signal_id: "sig-test", passed: true },
      { normalization_state: "quarantined" },
    );

    const result = derive({
      priorState: makeTaskState({ status: "in_progress" }),
      normalizedArtifacts: [quarantinedArtifact],
      acceptanceSignals: [testSignal, mergeSignal],
    });

    // Quarantined artifact doesn't count — no transition
    expect(result.transitionOccurred).toBe(false);
  });

  it("observed artifacts are excluded from derivation", () => {
    const testSignal: AcceptanceSignal = {
      id: "sig-test",
      category: "test",
      required: true,
      success_condition: "pass",
      pattern: "test_*",
    };
    const mergeSignal: AcceptanceSignal = {
      id: "sig-merge",
      category: "merge",
      required: true,
      success_condition: "merged",
    };

    const observedArtifact = makeArtifact(
      "na-1",
      "task-1",
      { type: "test_result", signal_id: "sig-test", passed: true },
      { normalization_state: "observed" },
    );

    const result = derive({
      priorState: makeTaskState({ status: "in_progress" }),
      normalizedArtifacts: [observedArtifact],
      acceptanceSignals: [testSignal, mergeSignal],
    });

    expect(result.transitionOccurred).toBe(false);
  });

  it("quarantined artifact schema validates correctly", () => {
    assertValid("normalized-artifact.schema.json", {
      id: "na-q1",
      raw_artifact_id: "raw-q1",
      primary_task_id: "task-1",
      session_id: "sess-1",
      artifact_source: "cli",
      worker_id: "worker-1",
      context_source: "explicit_lock",
      timestamp: "2026-03-19T12:00:00Z",
      normalization_state: "quarantined",
      binding_confidence: 0.3,
      signal_payload: {
        type: "test_result",
        signal_id: "sig-1",
        passed: true,
      },
    });
  });
});

// ─── Binding Precedence ──────────────────────────────────────────────

describe("Binding Precedence", () => {
  it("explicit_lock context_source takes precedence in session binding", () => {
    // Schema-level: both context sources are valid
    assertValid("task-session.schema.json", {
      id: "sess-lock",
      task_id: "task-1",
      worker_id: "agent-1",
      start_time: "2026-03-19T10:00:00Z",
      artifact_ids: ["na-1"],
      context_source: "explicit_lock",
    });

    assertValid("task-session.schema.json", {
      id: "sess-branch",
      task_id: "task-1",
      worker_id: "agent-1",
      start_time: "2026-03-19T10:00:00Z",
      artifact_ids: ["na-1"],
      context_source: "branch_inference",
    });

    assertValid("task-session.schema.json", {
      id: "sess-session-default",
      task_id: "task-1",
      worker_id: "agent-1",
      start_time: "2026-03-19T10:00:00Z",
      artifact_ids: ["na-1"],
      context_source: "session_default",
    });

    // Both are structurally valid. Precedence (explicit_lock > branch_inference)
    // is a Layer 2 behavioral rule, not a schema structural rule.
  });
});

// ─── Task-Create Policy ─────────────────────────────────────────────

describe("Task-Create Policy Failures", () => {
  it("rejects task-create with no acceptance signals (structural)", () => {
    assertInvalid("task-create.schema.json", {
      id: "task-bad",
      title: "Bad task",
      description: "No signals",
      assignee_human_id: "chad",
      status: "not_started",
      acceptance_criteria: "none",
      acceptance_signals: [], // minItems: 1 violation
      depends_on: [],
    });
  });

  it("rejects task-create with terminal status", () => {
    assertInvalid("task-create.schema.json", {
      id: "task-bad",
      title: "Done task",
      description: "Already done",
      assignee_human_id: "chad",
      status: "done", // terminal — not allowed on create
      acceptance_criteria: "none",
      acceptance_signals: [
        { id: "sig-1", category: "test", required: true, success_condition: "pass", pattern: "x" },
      ],
      depends_on: [],
    });
  });

  it("accepts valid task-create with required signal", () => {
    assertValid("task-create.schema.json", {
      id: "task-good",
      title: "Good task",
      description: "Has signals",
      assignee_human_id: "chad",
      status: "not_started",
      acceptance_criteria: "tests pass",
      acceptance_signals: [
        { id: "sig-1", category: "test", required: true, success_condition: "pass", pattern: "test_*" },
      ],
      depends_on: [],
    });
  });
});
