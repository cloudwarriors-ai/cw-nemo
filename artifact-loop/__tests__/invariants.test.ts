// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Hard invariant tests for the derivation helper.
 * ALL 9 INVARIANTS MUST PASS before proceeding to Phase 4.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { derive, resetDerivationState } from "./helpers/derivation-helper.js";
import type {
  AcceptanceSignal,
  DerivationInput,
  NormalizedArtifact,
  TaskState,
} from "./helpers/types.js";

// ─── Test Fixtures ───────────────────────────────────────────────────

const NOW = new Date("2026-03-19T12:00:00Z");
const RECENT = "2026-03-19T11:00:00Z"; // 1 hour ago, within window
const OLD = "2026-03-17T12:00:00Z"; // 2 days ago, outside 24h window

function makeTaskState(overrides: Partial<TaskState> = {}): TaskState {
  return {
    status: "not_started",
    task_confidence: 0,
    binding_confidence: 0,
    missing_inputs: [],
    ...overrides,
  };
}

function makeTestSignal(id: string, required = true): AcceptanceSignal {
  return {
    id,
    category: "test",
    required,
    success_condition: "test passes",
    pattern: "test_*",
  };
}

function makeFileSignal(id: string, required = true): AcceptanceSignal {
  return {
    id,
    category: "file",
    required,
    success_condition: "file exists",
    path: "src/index.ts",
  };
}

function makeMergeSignal(id: string): AcceptanceSignal {
  return {
    id,
    category: "merge",
    required: true,
    success_condition: "merged to main",
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
  // Mock Date.now to return a fixed time for deterministic tests
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

// ─── Invariant Tests ─────────────────────────────────────────────────

describe("Derivation Invariants", () => {
  it("1. Failure dominates success — required signal failure after a pass within derivation window keeps task blocked", () => {
    const testSignal = makeTestSignal("sig-test");
    const mergeSignal = makeMergeSignal("sig-merge");

    // Both a passing and failing test result within the window
    const passingArtifact = makeArtifact("na-1", "task-1", {
      type: "test_result",
      signal_id: "sig-test",
      passed: true,
    });

    const failingArtifact = makeArtifact("na-2", "task-1", {
      type: "test_result",
      signal_id: "sig-test",
      passed: false,
    });

    const input: DerivationInput = {
      priorState: makeTaskState({ status: "in_progress" }),
      normalizedArtifacts: [passingArtifact, failingArtifact],
      acceptanceSignals: [testSignal, mergeSignal],
    };

    const result = derive(input);

    expect(result.nextState.status).toBe("blocked");
    expect(result.transitionOccurred).toBe(true);
    expect(result.derivationRun).toBeDefined();
    expect(result.derivationRun!.rules_applied).toContain("required_signal_failure");
  });

  it("2. No transition without evidence — derive with no new artifacts and no override: transitionOccurred === false", () => {
    const input: DerivationInput = {
      priorState: makeTaskState({ status: "in_progress" }),
      normalizedArtifacts: [],
      acceptanceSignals: [makeTestSignal("sig-1")],
    };

    const result = derive(input);

    expect(result.transitionOccurred).toBe(false);
    expect(result.derivationRun).toBeUndefined();
    expect(result.nextState.status).toBe("in_progress");
  });

  it("3. Done only via merge or override — passing all test/file/command signals does not produce done", () => {
    const testSignal = makeTestSignal("sig-test");
    const fileSignal = makeFileSignal("sig-file");
    const mergeSignal = makeMergeSignal("sig-merge");

    const testPass = makeArtifact("na-1", "task-1", {
      type: "test_result",
      signal_id: "sig-test",
      passed: true,
    });

    const fileChange = makeArtifact("na-2", "task-1", {
      type: "file_change",
      signal_id: "sig-file",
      path: "src/index.ts",
      change_type: "modified",
    });

    const input: DerivationInput = {
      priorState: makeTaskState({ status: "in_progress" }),
      normalizedArtifacts: [testPass, fileChange],
      acceptanceSignals: [testSignal, fileSignal, mergeSignal],
    };

    const result = derive(input);

    // All non-merge signals pass, but merge hasn't happened → ready_for_review, NOT done
    expect(result.nextState.status).not.toBe("done");
    expect(result.nextState.status).toBe("ready_for_review");
  });

  it("4. Merge artifact produces done — normalized merge_result moves task to done", () => {
    const testSignal = makeTestSignal("sig-test");
    const mergeSignal = makeMergeSignal("sig-merge");

    const testPass = makeArtifact("na-1", "task-1", {
      type: "test_result",
      signal_id: "sig-test",
      passed: true,
    });

    const mergeResult = makeArtifact("na-2", "task-1", {
      type: "merge_result",
      signal_id: "sig-merge",
      merge_ref: "abc123",
      target_branch: "main",
    });

    const input: DerivationInput = {
      priorState: makeTaskState({ status: "ready_for_review" }),
      normalizedArtifacts: [testPass, mergeResult],
      acceptanceSignals: [testSignal, mergeSignal],
    };

    const result = derive(input);

    expect(result.nextState.status).toBe("done");
    expect(result.transitionOccurred).toBe(true);
    expect(result.derivationRun).toBeDefined();
    expect(result.derivationRun!.rules_applied).toContain("merge_completion");
  });

  it("5. needs_input requires tracked missing input — task-state with status=needs_input but empty missing_inputs fails schema validation", () => {
    // This is a schema-level invariant, tested in schema-validation.test.ts.
    // Here we verify the derivation helper also enforces it:
    // when transitioning to needs_input, missing_inputs must be populated.
    const input: DerivationInput = {
      priorState: makeTaskState({ status: "in_progress" }),
      normalizedArtifacts: [
        makeArtifact("na-1", "task-1", {
          type: "manual_event",
          event_type: "missing_input",
          description: "Need design review approval",
          by: "chad",
        }),
      ],
      acceptanceSignals: [makeTestSignal("sig-1"), makeMergeSignal("sig-merge")],
    };

    const result = derive(input);

    if (result.nextState.status === "needs_input") {
      expect(result.nextState.missing_inputs.length).toBeGreaterThan(0);
    }
  });

  it("6. Unrelated artifact does not clear needs_input — artifact bound to different signal doesn't resolve missing-input condition", () => {
    const missingInputState = makeTaskState({
      status: "needs_input",
      missing_inputs: [
        {
          type: "human_decision",
          source: "Need design review approval",
          detected_at: "2026-03-19T10:00:00Z",
        },
      ],
    });

    // Artifact bound to a completely different signal — should NOT resolve missing input
    const unrelatedArtifact = makeArtifact("na-1", "task-1", {
      type: "test_result",
      signal_id: "sig-unrelated",
      passed: true,
    });

    const input: DerivationInput = {
      priorState: missingInputState,
      normalizedArtifacts: [unrelatedArtifact],
      acceptanceSignals: [makeTestSignal("sig-test"), makeMergeSignal("sig-merge")],
    };

    const result = derive(input);

    // Missing input should still be unresolved
    const unresolvedMissing = result.nextState.missing_inputs.filter(
      (mi) => !mi.resolved_at,
    );
    expect(unresolvedMissing.length).toBeGreaterThan(0);
    expect(result.nextState.status).toBe("needs_input");
  });

  it("7. Replay does not create additional transitions — replayed artifacts must not create additional state transition or persisted derivation run", () => {
    const testSignal = makeTestSignal("sig-test");
    const mergeSignal = makeMergeSignal("sig-merge");

    const testPass = makeArtifact("na-1", "task-1", {
      type: "test_result",
      signal_id: "sig-test",
      passed: true,
    });

    // First derivation: not_started → in_progress (or ready_for_review)
    const input1: DerivationInput = {
      priorState: makeTaskState({ status: "in_progress" }),
      normalizedArtifacts: [testPass],
      acceptanceSignals: [testSignal, mergeSignal],
    };

    const result1 = derive(input1);

    // Second derivation with same artifacts but using result1's state as prior
    const input2: DerivationInput = {
      priorState: result1.nextState,
      normalizedArtifacts: [testPass], // same artifacts replayed
      acceptanceSignals: [testSignal, mergeSignal],
    };

    const result2 = derive(input2);

    // No additional transition should occur
    expect(result2.transitionOccurred).toBe(false);
    expect(result2.derivationRun).toBeUndefined();
    expect(result2.nextState.status).toBe(result1.nextState.status);
  });

  it("8. Recomputation with same inputs = no transition — derive(identical inputs) returns transitionOccurred === false", () => {
    const testSignal = makeTestSignal("sig-test");
    const mergeSignal = makeMergeSignal("sig-merge");

    const artifact = makeArtifact("na-1", "task-1", {
      type: "test_result",
      signal_id: "sig-test",
      passed: true,
    });

    // State is already ready_for_review (all non-merge satisfied)
    const priorState = makeTaskState({ status: "ready_for_review" });

    const input: DerivationInput = {
      priorState,
      normalizedArtifacts: [artifact],
      acceptanceSignals: [testSignal, mergeSignal],
    };

    const result = derive(input);

    expect(result.transitionOccurred).toBe(false);
    expect(result.derivationRun).toBeUndefined();
  });

  it("9. Old signals outside window — passing signal from >24h ago without current confirmation doesn't satisfy requirement", () => {
    const testSignal = makeTestSignal("sig-test");
    const mergeSignal = makeMergeSignal("sig-merge");

    // Test pass from 2 days ago — outside the 24h derivation window
    const oldArtifact = makeArtifact(
      "na-1",
      "task-1",
      {
        type: "test_result",
        signal_id: "sig-test",
        passed: true,
      },
      { timestamp: OLD },
    );

    const input: DerivationInput = {
      priorState: makeTaskState({ status: "in_progress" }),
      normalizedArtifacts: [oldArtifact],
      acceptanceSignals: [testSignal, mergeSignal],
    };

    const result = derive(input);

    // Old signal should not cause a transition
    expect(result.transitionOccurred).toBe(false);
    expect(result.nextState.status).toBe("in_progress");
  });
});
