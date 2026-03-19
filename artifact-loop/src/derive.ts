// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Pure derivation function. No storage, no side effects, no async, no retries.
 *
 * Canonical status transitions only:
 * - Readiness evaluation (required non-merge signals satisfied)
 * - Blocking (required signal failure, explicit blocker)
 * - Missing input handling (needs_input with tracked condition)
 * - Merge completion (done via merge signal)
 * - Override application (sets canonical status only)
 * - Replay/no-change semantics
 *
 * Explicitly out of scope: staleness evaluation, dependency propagation, briefing logic.
 */

import type {
  AcceptanceSignal,
  CanonicalStatus,
  DerivationInput,
  DerivationOutput,
  DerivationRun,
  MissingInput,
  NormalizedArtifact,
  SignalPayload,
  TaskState,
} from "./types.js";

/** 24-hour derivation window in milliseconds */
const DERIVATION_WINDOW_MS = 24 * 60 * 60 * 1000;

let derivationRunCounter = 0;

function generateRunId(): string {
  return `dr-${++derivationRunCounter}-${Date.now()}`;
}

/** Reset counter between test runs */
export function resetDerivationState(): void {
  derivationRunCounter = 0;
}

/**
 * Check whether an artifact is eligible for derivation.
 * Only "normalized" and "consumed_for_derivation" states are derivation-eligible.
 */
function isDerivationEligible(artifact: NormalizedArtifact): boolean {
  return (
    artifact.normalization_state === "normalized" ||
    artifact.normalization_state === "consumed_for_derivation"
  );
}

/**
 * Check whether an artifact's timestamp is within the derivation window.
 */
function isWithinWindow(
  artifactTimestamp: string,
  now: Date,
): boolean {
  const artifactTime = new Date(artifactTimestamp).getTime();
  const windowStart = now.getTime() - DERIVATION_WINDOW_MS;
  return artifactTime >= windowStart;
}

/**
 * Determine if a signal payload represents success for its acceptance signal.
 */
function isSignalSatisfied(
  payload: SignalPayload,
  signal: AcceptanceSignal,
): boolean {
  if (!("signal_id" in payload) || payload.signal_id !== signal.id) {
    return false;
  }

  switch (payload.type) {
    case "test_result":
      return payload.passed === true;
    case "file_change":
      return true; // file existence/change satisfies file signal
    case "command_result":
      return payload.exit_code === 0;
    case "merge_result":
      return true; // merge presence satisfies merge signal
    default:
      return false;
  }
}

/**
 * Determine if a signal payload represents failure for its acceptance signal.
 */
function isSignalFailed(
  payload: SignalPayload,
  signal: AcceptanceSignal,
): boolean {
  if (!("signal_id" in payload) || payload.signal_id !== signal.id) {
    return false;
  }

  switch (payload.type) {
    case "test_result":
      return payload.passed === false;
    case "command_result":
      return payload.exit_code !== 0;
    default:
      return false;
  }
}

interface SignalEvaluation {
  satisfied: boolean;
  failed: boolean;
  hasEvidence: boolean;
}

/**
 * Evaluate all acceptance signals against current artifacts within the derivation window.
 *
 * CRITICAL: Failure dominates success — if any required signal has a failure
 * within the window, it counts as failed even if there's also a success.
 */
function evaluateSignals(
  signals: AcceptanceSignal[],
  artifacts: NormalizedArtifact[],
  now: Date,
): Map<string, SignalEvaluation> {
  const results = new Map<string, SignalEvaluation>();

  for (const signal of signals) {
    let satisfied = false;
    let failed = false;
    let hasEvidence = false;

    for (const artifact of artifacts) {
      if (!isDerivationEligible(artifact)) continue;
      if (!isWithinWindow(artifact.timestamp, now)) continue;

      if (isSignalSatisfied(artifact.signal_payload, signal)) {
        satisfied = true;
        hasEvidence = true;
      }
      if (isSignalFailed(artifact.signal_payload, signal)) {
        failed = true;
        hasEvidence = true;
      }
    }

    // Failure dominates: if failed within window, signal is not satisfied
    if (failed) {
      satisfied = false;
    }

    results.set(signal.id, { satisfied, failed, hasEvidence });
  }

  return results;
}

/**
 * Core derivation function. Pure, deterministic, no side effects.
 */
export function derive(input: DerivationInput): DerivationOutput {
  const { priorState, normalizedArtifacts, acceptanceSignals, override } = input;
  const rulesApplied: string[] = [];
  const now = new Date();

  // ─── Override application ────────────────────────────────────────
  // Override sets canonical status only. It does not suppress incoming
  // artifacts, disable staleness tracking, or interfere with enrichment.
  if (override) {
    const overrideStatus = override.status;
    if (overrideStatus !== priorState.status) {
      const nextState: TaskState = {
        ...priorState,
        status: overrideStatus,
        // If overriding to needs_input without existing missing_inputs, add a placeholder
        missing_inputs:
          overrideStatus === "needs_input" && priorState.missing_inputs.length === 0
            ? [
                {
                  type: "human_decision",
                  source: `Override by ${override.by}: ${override.reason}`,
                  detected_at: override.timestamp,
                },
              ]
            : priorState.missing_inputs,
      };

      const derivationRun: DerivationRun = {
        id: generateRunId(),
        timestamp: override.timestamp,
        task_id: "", // caller must fill
        input_artifact_ids: normalizedArtifacts.map((a) => a.id),
        rules_applied: ["override_application"],
        prior_state: priorState.status,
        output_state: overrideStatus,
        input_override_id: override.id,
      };

      return {
        nextState,
        transitionOccurred: true,
        derivationRun,
      };
    }

    // Override to same status = no transition
    return {
      nextState: { ...priorState },
      transitionOccurred: false,
    };
  }

  // ─── No artifacts = no evidence = no transition ──────────────────
  const eligibleArtifacts = normalizedArtifacts.filter(
    (a) => isDerivationEligible(a) && isWithinWindow(a.timestamp, now),
  );

  if (eligibleArtifacts.length === 0) {
    return {
      nextState: { ...priorState },
      transitionOccurred: false,
    };
  }

  // ─── Evaluate signals ────────────────────────────────────────────
  const signalEvals = evaluateSignals(acceptanceSignals, normalizedArtifacts, now);

  const requiredSignals = acceptanceSignals.filter((s) => s.required);
  const requiredNonMerge = requiredSignals.filter((s) => s.category !== "merge");
  const mergeSignals = requiredSignals.filter((s) => s.category === "merge");

  // Check for any required signal failure
  const hasRequiredFailure = requiredSignals.some((s) => {
    const eval_ = signalEvals.get(s.id);
    return eval_?.failed === true;
  });

  // Check if all required non-merge signals are satisfied
  const allNonMergeSatisfied = requiredNonMerge.every((s) => {
    const eval_ = signalEvals.get(s.id);
    return eval_?.satisfied === true;
  });

  // Check for merge completion
  const hasMergeCompletion = mergeSignals.some((s) => {
    const eval_ = signalEvals.get(s.id);
    return eval_?.satisfied === true;
  });

  // ─── Detect missing inputs ──────────────────────────────────────
  // Check if any artifacts indicate missing input conditions
  const newMissingInputs = detectMissingInputs(normalizedArtifacts, now);

  // Check if existing missing inputs have been resolved by new artifacts
  const resolvedMissing = resolveExistingMissingInputs(
    priorState.missing_inputs,
    normalizedArtifacts,
    now,
  );

  let nextStatus: CanonicalStatus = priorState.status;
  let nextMissingInputs = [...resolvedMissing];

  // ─── State transition rules (ordered by priority) ────────────────

  // Rule 1: Merge completion → done
  if (hasMergeCompletion && allNonMergeSatisfied) {
    nextStatus = "done";
    rulesApplied.push("merge_completion");
  }
  // Rule 2: Required signal failure → blocked
  else if (hasRequiredFailure) {
    nextStatus = "blocked";
    rulesApplied.push("required_signal_failure");
  }
  // Rule 3: Unresolved missing inputs → needs_input
  else if (newMissingInputs.length > 0) {
    nextMissingInputs = [...nextMissingInputs, ...newMissingInputs];
    nextStatus = "needs_input";
    rulesApplied.push("missing_input_detected");
  }
  // Rule 4: Existing unresolved missing inputs remain
  else if (
    nextMissingInputs.some((mi) => !mi.resolved_at) &&
    priorState.status === "needs_input"
  ) {
    nextStatus = "needs_input";
    rulesApplied.push("missing_input_persists");
  }
  // Rule 5: All non-merge signals satisfied → ready_for_review
  else if (allNonMergeSatisfied && requiredNonMerge.length > 0) {
    nextStatus = "ready_for_review";
    rulesApplied.push("readiness_evaluation");
  }
  // Rule 6: Some evidence of progress → in_progress
  else if (
    eligibleArtifacts.length > 0 &&
    priorState.status === "not_started"
  ) {
    nextStatus = "in_progress";
    rulesApplied.push("progress_detected");
  }

  // ─── Compute confidence ──────────────────────────────────────────
  const taskConfidence = computeTaskConfidence(
    acceptanceSignals,
    signalEvals,
    nextStatus,
  );

  const bindingConfidence = computeBindingConfidence(eligibleArtifacts);

  // ─── Build output ────────────────────────────────────────────────
  const nextState: TaskState = {
    status: nextStatus,
    task_confidence: taskConfidence,
    binding_confidence: bindingConfidence,
    missing_inputs: nextMissingInputs,
  };

  const transitionOccurred = nextStatus !== priorState.status;

  if (transitionOccurred) {
    const derivationRun: DerivationRun = {
      id: generateRunId(),
      timestamp: now.toISOString(),
      task_id: "", // caller must fill
      input_artifact_ids: eligibleArtifacts.map((a) => a.id),
      rules_applied: rulesApplied,
      prior_state: priorState.status,
      output_state: nextStatus,
    };

    return { nextState, transitionOccurred, derivationRun };
  }

  return { nextState, transitionOccurred: false };
}

// ─── Helper functions ────────────────────────────────────────────────

function detectMissingInputs(
  artifacts: NormalizedArtifact[],
  now: Date,
): MissingInput[] {
  const missing: MissingInput[] = [];

  for (const artifact of artifacts) {
    if (!isDerivationEligible(artifact)) continue;
    if (!isWithinWindow(artifact.timestamp, now)) continue;

    // manual_event or runtime_event with specific event_types could indicate missing inputs
    if (artifact.signal_payload.type === "manual_event") {
      if (artifact.signal_payload.event_type === "missing_input") {
        missing.push({
          type: "human_decision",
          source: artifact.signal_payload.description,
          detected_at: artifact.timestamp,
        });
      }
    }

    if (artifact.signal_payload.type === "runtime_event") {
      if (artifact.signal_payload.event_type === "missing_dependency") {
        missing.push({
          type: "dependency",
          source: artifact.signal_payload.detail,
          detected_at: artifact.timestamp,
        });
      }
      if (artifact.signal_payload.event_type === "missing_external_resource") {
        missing.push({
          type: "external_resource",
          source: artifact.signal_payload.detail,
          detected_at: artifact.timestamp,
        });
      }
    }
  }

  return missing;
}

function resolveExistingMissingInputs(
  existingInputs: MissingInput[],
  artifacts: NormalizedArtifact[],
  now: Date,
): MissingInput[] {
  return existingInputs.map((mi) => {
    if (mi.resolved_at) return mi; // already resolved

    // Check if any artifact explicitly resolves this missing input
    for (const artifact of artifacts) {
      if (!isDerivationEligible(artifact)) continue;
      if (!isWithinWindow(artifact.timestamp, now)) continue;

      if (
        artifact.signal_payload.type === "manual_event" &&
        artifact.signal_payload.event_type === "input_provided" &&
        artifact.signal_payload.description === mi.source
      ) {
        return {
          ...mi,
          resolved_at: artifact.timestamp,
          resolution_artifact_id: artifact.id,
        };
      }
    }

    return mi;
  });
}

function computeTaskConfidence(
  signals: AcceptanceSignal[],
  evals: Map<string, SignalEvaluation>,
  status: CanonicalStatus,
): number {
  if (status === "done") return 1.0;
  if (status === "not_started") return 0.0;

  const required = signals.filter((s) => s.required);
  if (required.length === 0) return 0.5;

  const satisfiedCount = required.filter((s) => {
    const eval_ = evals.get(s.id);
    return eval_?.satisfied === true;
  }).length;

  return Math.round((satisfiedCount / required.length) * 100) / 100;
}

function computeBindingConfidence(artifacts: NormalizedArtifact[]): number {
  if (artifacts.length === 0) return 0;
  const total = artifacts.reduce((sum, a) => sum + a.binding_confidence, 0);
  return Math.round((total / artifacts.length) * 100) / 100;
}
