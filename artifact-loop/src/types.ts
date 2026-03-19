// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Canonical type definitions for the artifact-loop system.
 * Derived from the JSON Schema contracts in contracts/.
 */

export type CanonicalStatus =
  | "not_started"
  | "in_progress"
  | "needs_input"
  | "blocked"
  | "ready_for_review"
  | "done";

export type NormalizationState =
  | "observed"
  | "bound"
  | "quarantined"
  | "normalized"
  | "consumed_for_derivation";

export type SignalCategory = "test" | "file" | "command" | "merge";

export type MissingInputType = "dependency" | "human_decision" | "external_resource";

// ─── Signal Payloads ─────────────────────────────────────────────────

export interface TestResultPayload {
  type: "test_result";
  signal_id: string;
  passed: boolean;
  output?: string;
  error?: string;
}

export interface FileChangePayload {
  type: "file_change";
  signal_id: string;
  path: string;
  change_type: "created" | "modified" | "deleted";
}

export interface CommandResultPayload {
  type: "command_result";
  signal_id: string;
  exit_code: number;
  stdout?: string;
  stderr?: string;
}

export interface MergeResultPayload {
  type: "merge_result";
  signal_id: string;
  merge_ref: string;
  target_branch: string;
}

export interface ManualEventPayload {
  type: "manual_event";
  signal_id?: string;
  event_type: string;
  description: string;
  by: string;
}

export interface RuntimeEventPayload {
  type: "runtime_event";
  signal_id?: string;
  event_type: string;
  source: string;
  detail: string;
}

export type SignalPayload =
  | TestResultPayload
  | FileChangePayload
  | CommandResultPayload
  | MergeResultPayload
  | ManualEventPayload
  | RuntimeEventPayload;

// ─── Acceptance Signal ───────────────────────────────────────────────

export interface AcceptanceSignal {
  id: string;
  category: SignalCategory;
  required: boolean;
  success_condition: string;
  relevance_scope?: string;
  weight?: number;
  pattern?: string;
  path?: string;
  command?: string;
}

// ─── Missing Input ───────────────────────────────────────────────────

export interface MissingInput {
  type: MissingInputType;
  source: string;
  detected_at: string;
  resolved_at?: string;
  resolution_artifact_id?: string;
}

// ─── Task State ──────────────────────────────────────────────────────

export interface TaskState {
  status: CanonicalStatus;
  task_confidence: number;
  binding_confidence: number;
  missing_inputs: MissingInput[];
}

// ─── Normalized Artifact ─────────────────────────────────────────────

export interface NormalizedArtifact {
  id: string;
  raw_artifact_id: string;
  primary_task_id: string;
  session_id: string;
  timestamp: string;
  normalization_state: NormalizationState;
  binding_confidence: number;
  signal_payload: SignalPayload;
}

// ─── Derivation Run ─────────────────────────────────────────────────

export interface DerivationRun {
  id: string;
  timestamp: string;
  task_id: string;
  input_artifact_ids: string[];
  rules_applied: string[];
  prior_state: CanonicalStatus;
  output_state: CanonicalStatus;
  input_override_id?: string;
}

// ─── Derivation I/O ─────────────────────────────────────────────────

export interface DerivationInput {
  priorState: TaskState;
  normalizedArtifacts: NormalizedArtifact[];
  acceptanceSignals: AcceptanceSignal[];
  override?: {
    id: string;
    status: CanonicalStatus;
    reason: string;
    by: string;
    timestamp: string;
  };
}

export interface DerivationOutput {
  nextState: TaskState;
  /** true only when derivation produces a materially different canonical status than priorState */
  transitionOccurred: boolean;
  /** present only when transitionOccurred is true */
  derivationRun?: DerivationRun;
}

// ─── Raw Artifact ───────────────────────────────────────────────────

export interface RawArtifact {
  id: string;
  type: string;
  timestamp: string;
  source: string;
  pointer: string;
  summary: string;
  raw_payload?: unknown;
}

// ─── Task ───────────────────────────────────────────────────────────

export interface Task {
  id: string;
  title: string;
  description: string;
  assignee_human_id: string;
  assignee_agent_id?: string;
  status: CanonicalStatus;
  acceptance_criteria: string;
  acceptance_signals: AcceptanceSignal[];
  depends_on: string[];
  last_activity_at: string;
  override?: Override;
}

// ─── Task Create ────────────────────────────────────────────────────

export interface TaskCreate {
  id: string;
  title: string;
  description: string;
  assignee_human_id: string;
  assignee_agent_id?: string;
  status: Exclude<CanonicalStatus, "done">;
  acceptance_criteria: string;
  acceptance_signals: AcceptanceSignal[];
  depends_on: string[];
}

// ─── Override ───────────────────────────────────────────────────────

export interface Override {
  status: CanonicalStatus;
  reason: string;
  by: string;
  timestamp: string;
}

// ─── Normalization Context ──────────────────────────────────────────

export interface NormalizationContext {
  primary_task_id: string;
  session_id: string;
  worker_id: string;
  context_source: "explicit_lock" | "explicit_event" | "branch_inference";
}

// ─── Ingest Result ──────────────────────────────────────────────────

export interface IngestResult {
  normalizedArtifact: NormalizedArtifact;
  derivationOutput: DerivationOutput;
}
