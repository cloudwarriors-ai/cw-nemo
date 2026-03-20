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
export type ContextSource =
  | "explicit_lock"
  | "session_default"
  | "explicit_event"
  | "branch_inference";

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

export interface GitDiffSummaryFile {
  path: string;
  change_type: "created" | "modified" | "deleted";
  previous_path?: string;
}

export interface GitDiffSummaryPayload {
  type: "git_diff_summary";
  mode: "working_tree" | "staged";
  files: GitDiffSummaryFile[];
  base_ref?: string;
  head_ref?: string;
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
  | GitDiffSummaryPayload
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
  artifact_source?: string;
  worker_id?: string;
  worker_agent_id?: string;
  context_source?: ContextSource;
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

// ─── Signal Status Read Model ───────────────────────────────────────

export type SignalDisplayStatus = "satisfied" | "failed" | "not_yet_satisfied";

export interface SignalStatusView {
  signal: AcceptanceSignal;
  status: SignalDisplayStatus;
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
  project_id?: string;
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

// ─── Organization ──────────────────────────────────────────────────

export interface Organization {
  id: string;
  name: string;
  timezone: string;
  created_at: string;
  updated_at: string;
}

export interface OrganizationBootstrapRequest {
  organization: {
    id: string;
    name: string;
    timezone: string;
  };
  initial_team: {
    id: string;
    name: string;
    description: string;
  };
  initial_member: {
    id: string;
    display_name: string;
    timezone: string;
  };
  initial_agent: {
    id: string;
    label: string;
    connector_type: string;
    active?: boolean;
  };
}

export interface OrganizationBootstrapResult {
  organization: Organization;
  team: Team;
  membership: TeamMembership;
  member: Worker;
  agent: WorkerAgent;
}

export type TeamMembershipRole = "admin" | "lead" | "worker";
export type TeamMembershipStatus = "active" | "inactive";

export interface Team {
  id: string;
  organization_id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface TeamCreate {
  id: string;
  name: string;
  description: string;
  created_by_worker_id: string;
}

export interface TeamMembership {
  member_id: string;
  team_id: string;
  role: TeamMembershipRole;
  status: TeamMembershipStatus;
  created_at: string;
  updated_at: string;
}

export interface TeamMembershipCreate {
  member_id: string;
  role: TeamMembershipRole;
  status?: TeamMembershipStatus;
  display_name?: string;
  timezone?: string;
  worker_role?: string;
  added_by_worker_id: string;
}

// ─── Project ────────────────────────────────────────────────────────

export interface Project {
  id: string;
  team_id: string;
  title: string;
  description: string;
  owner_worker_id: string;
  definition?: ProjectDefinition;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreate {
  id: string;
  team_id: string;
  title: string;
  description: string;
  owner_worker_id: string;
  definition?: ProjectDefinition;
}

export interface ProjectTaskLinkCreate {
  task_id: string;
}

export interface ProjectDefinition {
  goal: string;
  scope: string[];
  deliverables: string[];
  constraints: string[];
  definition_of_done: string;
}

export interface TaskDraft {
  id: string;
  title: string;
  description: string;
  assignee_role_hint?: string;
  acceptance_criteria: string;
  acceptance_signals: AcceptanceSignal[];
  depends_on_draft_ids: string[];
  rationale: string;
}

export type TaskDraftSetStatus = "draft" | "approved" | "rejected";

export interface TaskDraftSet {
  id: string;
  project_id: string;
  status: TaskDraftSetStatus;
  generated_by_agent_id: string;
  generated_at: string;
  approved_at?: string;
  approved_by_worker_id?: string;
  rejected_at?: string;
  rejected_by_worker_id?: string;
  drafts: TaskDraft[];
}

export interface TaskDraftSetGenerateRequest {
  generated_by_agent_id: string;
  drafts: TaskDraft[];
}

export interface TaskDraftSetApproveRequest {
  approved_by_worker_id: string;
}

export interface TaskDraftSetRejectRequest {
  rejected_by_worker_id: string;
}

export interface Worker {
  id: string;
  display_name: string;
  role: string;
  timezone: string;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkerCreate {
  id: string;
  display_name: string;
  role: string;
  timezone: string;
  active?: boolean;
}

export interface WorkerAgent {
  id: string;
  worker_id: string;
  label: string;
  connector_type: string;
  active: boolean;
  created_at: string;
  updated_at: string;
  last_seen_at?: string;
}

export interface WorkerAgentCreate {
  id: string;
  label: string;
  connector_type: string;
  active?: boolean;
}

export type InboxItemKind = "assignment" | "reassignment" | "message" | "brief";
export type InboxItemStatus = "pending" | "acknowledged" | "superseded" | "closed";

export interface InboxPayloadRef {
  type: "assignment" | "message" | "brief_run";
  id: string;
}

export interface InboxItem {
  id: string;
  recipient_worker_id: string;
  recipient_agent_id?: string;
  project_id: string;
  task_id?: string;
  kind: InboxItemKind;
  status: InboxItemStatus;
  created_at: string;
  acknowledged_at?: string;
  payload_ref: InboxPayloadRef;
}

export type TaskMessageKind = "ping" | "reply" | "note";

export interface TaskMessage {
  id: string;
  project_id: string;
  task_id: string;
  sender_worker_id: string;
  sender_agent_id?: string;
  recipient_worker_id: string;
  recipient_agent_id?: string;
  kind: TaskMessageKind;
  body: string;
  created_at: string;
  acknowledged_at?: string;
}

export interface TaskMessageCreate {
  sender_worker_id: string;
  sender_agent_id?: string;
  recipient_worker_id: string;
  recipient_agent_id?: string;
  kind: TaskMessageKind;
  body: string;
}

export interface ProjectBriefSchedule {
  project_id: string;
  owner_worker_id: string;
  timezone: string;
  delivery_hour_local: number;
  enabled: boolean;
  last_run_at?: string;
  next_run_at?: string;
}

export interface ProjectBriefScheduleUpsert {
  owner_worker_id: string;
  timezone: string;
  delivery_hour_local: number;
  enabled: boolean;
}

export interface ProjectBriefRun {
  id: string;
  project_id: string;
  generated_at: string;
  window_start: string;
  window_end: string;
  brief: ProjectBrief;
}

export interface ScheduledBriefRunResult {
  generated_count: number;
  generated_project_ids: string[];
}

export interface ProjectTaskListItem {
  id: string;
  title: string;
  status: CanonicalStatus;
  assignee_human_id: string;
  assignee_agent_id?: string;
  last_activity_at: string;
}

export interface ProjectSummary {
  project: Project;
  total_tasks: number;
  counts_by_status: Record<CanonicalStatus, number>;
  buckets: {
    blocked: ProjectTaskListItem[];
    needs_input: ProjectTaskListItem[];
    ready_for_review: ProjectTaskListItem[];
  };
  last_activity_at: string | null;
}

export interface ProjectHumanSummaryGroup {
  assignee_human_id: string;
  tasks: ProjectTaskListItem[];
}

export interface ProjectAgentSummaryGroup {
  assignee_agent_id: string;
  tasks: ProjectTaskListItem[];
}

export interface ProjectWorkerSummary {
  project_id: string;
  by_human: ProjectHumanSummaryGroup[];
  by_agent: ProjectAgentSummaryGroup[];
}

export interface ProjectBriefMovementItem {
  task_id: string;
  task_title: string;
  assignee_human_id: string;
  assignee_agent_id?: string;
  changed_at: string;
  from_status: CanonicalStatus;
  to_status: CanonicalStatus;
  rules_applied: string[];
}

export type ProjectBriefAttentionKind = "blocked" | "needs_input" | "ready_for_review";

export interface ProjectBriefAttentionItem {
  kind: ProjectBriefAttentionKind;
  task: ProjectTaskListItem;
  reason: string;
}

export interface ProjectBriefWorkerGroup {
  worker_id: string;
  tasks: ProjectTaskListItem[];
  recent_activity_at: string;
  artifact_count: number;
}

export interface ProjectBrief {
  project: Project;
  generated_at: string;
  snapshot: {
    total_tasks: number;
    counts_by_status: Record<CanonicalStatus, number>;
    last_activity_at: string | null;
  };
  recent_movement: ProjectBriefMovementItem[];
  blocked: ProjectTaskListItem[];
  needs_input: ProjectTaskListItem[];
  ready_for_review: ProjectTaskListItem[];
  by_worker: ProjectBriefWorkerGroup[];
  by_human: ProjectHumanSummaryGroup[];
  by_agent: ProjectAgentSummaryGroup[];
  lead_attention_items: ProjectBriefAttentionItem[];
  rendered_text: string;
}

// ─── Assignment ─────────────────────────────────────────────────────

export interface Assignment {
  id: string;
  task_id: string;
  assignee_human_id: string;
  assignee_agent_id?: string;
  assigned_at: string;
  assigned_by?: string;
}

export interface AssignmentCreate {
  assignee_human_id: string;
  assignee_agent_id?: string;
  assigned_by?: string;
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
  worker_agent_id?: string;
  context_source: ContextSource;
}

// ─── Ingest Result ──────────────────────────────────────────────────

export interface IngestResult {
  normalizedArtifact: NormalizedArtifact;
  derivationOutput: DerivationOutput;
}

export interface IngestRequest {
  artifact: RawArtifact;
  context: NormalizationContext;
}

// ─── Usage Telemetry ────────────────────────────────────────────────

export interface TaskUseEvent {
  kind: "task_use";
  timestamp: string;
  action: "set" | "change" | "clear";
  task_id?: string;
  previous_task_id?: string;
}

export interface CommandResolutionEvent {
  kind: "command_resolution";
  timestamp: string;
  command_name: string;
  task_id: string;
  context_source: "explicit_lock" | "session_default";
  override_session: boolean;
}

export interface OverrideAppliedEvent {
  kind: "override_applied";
  timestamp: string;
  task_id: string;
  resulting_status: CanonicalStatus;
}

export type UsageEvent = TaskUseEvent | CommandResolutionEvent | OverrideAppliedEvent;

export interface UsageStats {
  task_use: {
    set: number;
    change: number;
    clear: number;
  };
  command_resolution: {
    explicit_lock: number;
    session_default: number;
    explicit_over_session_override: number;
  };
  artifacts_by_type: Record<string, number>;
  override_by_resulting_status: Partial<Record<CanonicalStatus, number>>;
  evidence_buckets: {
    manual_only: number;
    automatic_any: number;
    merge_only: number;
    none: number;
  };
}
