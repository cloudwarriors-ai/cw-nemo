// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type {
  DerivationRun,
  InboxItem,
  Organization,
  Project,
  ProjectBriefSchedule,
  ProjectSummary,
  ProjectTaskListItem,
  ProjectWorkerSummary,
  SignalStatusView,
  Task,
  TaskDraftSet,
  TaskMessage,
  TaskState,
  Team,
  TeamMembership,
  UsageStats,
  Worker,
  WorkerAgent,
} from "../../types.js";

export function formatJson(data: unknown): string {
  return JSON.stringify(data, null, 2);
}

export function formatTaskReference(taskId: string, fromSession = false): string {
  return fromSession ? `${taskId} (from session)` : taskId;
}

function formatSignalState(status: SignalStatusView["status"]): string {
  switch (status) {
    case "satisfied":
      return "satisfied";
    case "failed":
      return "failed";
    default:
      return "not yet satisfied";
  }
}

function buildNextLikelyStep(signalStatuses: SignalStatusView[]): string | undefined {
  const nextSignal = signalStatuses.find(
    ({ signal, status }) => signal.required && status !== "satisfied",
  );
  if (!nextSignal) return undefined;

  const { signal } = nextSignal;
  switch (signal.category) {
    case "test":
      return `artifact-loop run --signal-id ${signal.id} -- <command>`;
    case "command":
      return `artifact-loop run --kind command --signal-id ${signal.id} -- <command>`;
    case "merge":
      return `artifact-loop emit merge --signal-id ${signal.id} --ref <ref> --branch <branch>`;
    case "file":
      return `Produce file evidence for ${signal.path ?? signal.id}`;
  }
}

export function formatTaskStatus(
  task: Task,
  state: TaskState,
  fromSession = false,
  signalStatuses: SignalStatusView[] = [],
): string {
  const lines: string[] = [
    `Task: ${formatTaskReference(task.id, fromSession)}`,
    `Title: ${task.title}`,
    `Status: ${state.status}`,
    `Confidence: ${(state.task_confidence * 100).toFixed(0)}%`,
    `Binding: ${(state.binding_confidence * 100).toFixed(0)}%`,
  ];

  if (state.missing_inputs.length > 0) {
    lines.push(`Missing inputs:`);
    for (const mi of state.missing_inputs) {
      const resolved = mi.resolved_at ? " (resolved)" : "";
      lines.push(`  - [${mi.type}] ${mi.source}${resolved}`);
    }
  }

  if (task.override) {
    lines.push(`Override: ${task.override.status} by ${task.override.by} — ${task.override.reason}`);
  }

  if (signalStatuses.length > 0) {
    lines.push("Signals:");
    for (const { signal, status } of signalStatuses) {
      lines.push(
        `  [${signal.id}] (${signal.category}, ${signal.required ? "required" : "optional"}) ${formatSignalState(status)}`,
      );
    }

    const nextLikelyStep = buildNextLikelyStep(signalStatuses);
    if (nextLikelyStep) {
      lines.push("Next likely step:");
      lines.push(`  ${nextLikelyStep}`);
    }
  }

  return lines.join("\n");
}

export function formatDerivationHistory(taskId: string, runs: DerivationRun[], fromSession = false): string {
  const lines: string[] = [`Task: ${formatTaskReference(taskId, fromSession)}`];

  if (runs.length === 0) {
    lines.push("No derivation history.");
    return lines.join("\n");
  }

  lines.push(
    ...runs.map((run, i) => {
      const rules = run.rules_applied.join(", ");
      const override = run.input_override_id ? ` (override: ${run.input_override_id})` : "";
      return `${i + 1}. ${run.prior_state} → ${run.output_state}  [${rules}]${override}  (${run.timestamp})`;
    }),
  );

  return lines.join("\n");
}

export function formatUsageStats(stats: UsageStats): string {
  const artifactEntries = Object.entries(stats.artifacts_by_type).sort(([a], [b]) => a.localeCompare(b));
  const overrideEntries = Object.entries(stats.override_by_resulting_status).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  const lines: string[] = [
    "Usage Stats",
    `Task use: set=${stats.task_use.set} change=${stats.task_use.change} clear=${stats.task_use.clear}`,
    `Command resolution: explicit_lock=${stats.command_resolution.explicit_lock} session_default=${stats.command_resolution.session_default} explicit_over_session_override=${stats.command_resolution.explicit_over_session_override}`,
    "Artifacts by type:",
  ];

  if (artifactEntries.length === 0) {
    lines.push("  none");
  } else {
    for (const [type, count] of artifactEntries) {
      lines.push(`  ${type}: ${count}`);
    }
  }

  lines.push("Override by resulting status:");
  if (overrideEntries.length === 0) {
    lines.push("  none");
  } else {
    for (const [status, count] of overrideEntries) {
      lines.push(`  ${status}: ${count}`);
    }
  }

  lines.push(
    `Evidence buckets: automatic_any=${stats.evidence_buckets.automatic_any} manual_only=${stats.evidence_buckets.manual_only} merge_only=${stats.evidence_buckets.merge_only} none=${stats.evidence_buckets.none}`,
  );

  return lines.join("\n");
}

function formatTaskStub(task: ProjectTaskListItem | Task): string {
  const assigneeAgent = task.assignee_agent_id ? ` / ${task.assignee_agent_id}` : "";
  return `${task.id} [${task.status}] ${task.title} (${task.assignee_human_id}${assigneeAgent})`;
}

function pushTaskSection(lines: string[], title: string, tasks: ProjectTaskListItem[] | Task[]): void {
  lines.push(title);
  if (tasks.length === 0) {
    lines.push("  none");
    return;
  }
  for (const task of tasks) {
    lines.push(`  - ${formatTaskStub(task)}`);
  }
}

export function formatProject(project: Project): string {
  const lines = [
    `Project: ${project.id}`,
    `Team: ${project.team_id}`,
    `Title: ${project.title}`,
    `Description: ${project.description}`,
    `Owner worker: ${project.owner_worker_id}`,
    `Created: ${project.created_at}`,
    `Updated: ${project.updated_at}`,
  ];

  if (project.definition) {
    lines.push(`Goal: ${project.definition.goal}`);
    lines.push(`Definition of done: ${project.definition.definition_of_done}`);
    lines.push(`Scope: ${project.definition.scope.length > 0 ? project.definition.scope.join(", ") : "none"}`);
    lines.push(`Deliverables: ${project.definition.deliverables.length > 0 ? project.definition.deliverables.join(", ") : "none"}`);
    lines.push(`Constraints: ${project.definition.constraints.length > 0 ? project.definition.constraints.join(", ") : "none"}`);
  }

  return lines.join("\n");
}

export function formatProjects(projects: Project[]): string {
  const lines = ["Projects"];
  if (projects.length === 0) {
    lines.push("  none");
    return lines.join("\n");
  }
  for (const project of projects) {
    lines.push(`  - ${project.id}: ${project.title}`);
  }
  return lines.join("\n");
}

export function formatOrganization(organization: Organization): string {
  return [
    `Organization: ${organization.id}`,
    `Name: ${organization.name}`,
    `Timezone: ${organization.timezone}`,
    `Created: ${organization.created_at}`,
    `Updated: ${organization.updated_at}`,
  ].join("\n");
}

export function formatTeams(teams: Team[]): string {
  const lines = ["Teams"];
  if (teams.length === 0) {
    lines.push("  none");
    return lines.join("\n");
  }
  for (const team of teams) {
    lines.push(`  - ${team.id}: ${team.name}`);
  }
  return lines.join("\n");
}

export function formatTeam(team: Team): string {
  return [
    `Team: ${team.id}`,
    `Organization: ${team.organization_id}`,
    `Name: ${team.name}`,
    `Description: ${team.description}`,
    `Created: ${team.created_at}`,
    `Updated: ${team.updated_at}`,
  ].join("\n");
}

export function formatTeamMembers(teamId: string, memberships: TeamMembership[]): string {
  const lines = [`Team members: ${teamId}`];
  if (memberships.length === 0) {
    lines.push("  none");
    return lines.join("\n");
  }
  for (const membership of memberships) {
    lines.push(`  - ${membership.member_id}: ${membership.role} (${membership.status})`);
  }
  return lines.join("\n");
}

export function formatProjectSummary(summary: ProjectSummary): string {
  const { project, counts_by_status, buckets, last_activity_at, total_tasks } = summary;
  const statusCounts = Object.entries(counts_by_status)
    .map(([status, count]) => `${status}=${count}`)
    .join(" ");
  const lines = [
    `Project: ${project.id}`,
    `Title: ${project.title}`,
    `Total tasks: ${total_tasks}`,
    `Counts by status: ${statusCounts}`,
    `Last activity: ${last_activity_at ?? "none"}`,
  ];

  pushTaskSection(lines, "Blocked:", buckets.blocked);
  pushTaskSection(lines, "Needs input:", buckets.needs_input);
  pushTaskSection(lines, "Ready for review:", buckets.ready_for_review);

  return lines.join("\n");
}

export function formatProjectWorkerSummary(summary: ProjectWorkerSummary): string {
  const lines = [`Project worker summary: ${summary.project_id}`];

  lines.push("By human:");
  if (summary.by_human.length === 0) {
    lines.push("  none");
  } else {
    for (const group of summary.by_human) {
      lines.push(`  ${group.assignee_human_id}:`);
      for (const task of group.tasks) {
        lines.push(`    - ${formatTaskStub(task)}`);
      }
    }
  }

  lines.push("By agent:");
  if (summary.by_agent.length === 0) {
    lines.push("  none");
  } else {
    for (const group of summary.by_agent) {
      lines.push(`  ${group.assignee_agent_id}:`);
      for (const task of group.tasks) {
        lines.push(`    - ${formatTaskStub(task)}`);
      }
    }
  }

  return lines.join("\n");
}

export function formatProjectTasks(tasks: Task[]): string {
  const lines = ["Project tasks"];
  if (tasks.length === 0) {
    lines.push("  none");
    return lines.join("\n");
  }
  for (const task of tasks) {
    lines.push(`  - ${formatTaskStub(task)}`);
  }
  return lines.join("\n");
}

export function formatTaskDraftSets(draftSets: TaskDraftSet[]): string {
  const lines = ["Task draft sets"];
  if (draftSets.length === 0) {
    lines.push("  none");
    return lines.join("\n");
  }
  for (const draftSet of draftSets) {
    lines.push(`  - ${draftSet.id} [${draftSet.status}] drafts=${draftSet.drafts.length} generated_by=${draftSet.generated_by_agent_id}`);
  }
  return lines.join("\n");
}

export function formatTaskDraftSet(draftSet: TaskDraftSet): string {
  const lines = [
    `Draft set: ${draftSet.id}`,
    `Project: ${draftSet.project_id}`,
    `Status: ${draftSet.status}`,
    `Generated by: ${draftSet.generated_by_agent_id}`,
    `Generated at: ${draftSet.generated_at}`,
  ];
  if (draftSet.approved_by_worker_id) {
    lines.push(`Approved by: ${draftSet.approved_by_worker_id} at ${draftSet.approved_at}`);
  }
  if (draftSet.rejected_by_worker_id) {
    lines.push(`Rejected by: ${draftSet.rejected_by_worker_id} at ${draftSet.rejected_at}`);
  }
  lines.push("Drafts:");
  if (draftSet.drafts.length === 0) {
    lines.push("  none");
  } else {
    for (const draft of draftSet.drafts) {
      lines.push(`  - ${draft.id}: ${draft.title}`);
      lines.push(`    role_hint: ${draft.assignee_role_hint ?? "none"}`);
      lines.push(`    acceptance: ${draft.acceptance_criteria}`);
      lines.push(`    rationale: ${draft.rationale}`);
    }
  }
  return lines.join("\n");
}

export function formatWorker(worker: Worker): string {
  return [
    `Worker: ${worker.id}`,
    `Name: ${worker.display_name}`,
    `Role: ${worker.role}`,
    `Timezone: ${worker.timezone}`,
    `Active: ${worker.active ? "yes" : "no"}`,
  ].join("\n");
}

export function formatWorkers(workers: Worker[]): string {
  const lines = ["Workers"];
  if (workers.length === 0) {
    lines.push("  none");
    return lines.join("\n");
  }
  for (const worker of workers) {
    lines.push(`  - ${worker.id}: ${worker.display_name} (${worker.role})`);
  }
  return lines.join("\n");
}

export function formatWorkerAgents(workerId: string, agents: WorkerAgent[]): string {
  const lines = [`Worker agents: ${workerId}`];
  if (agents.length === 0) {
    lines.push("  none");
    return lines.join("\n");
  }
  for (const agent of agents) {
    lines.push(`  - ${agent.id}: ${agent.label} (${agent.connector_type}, ${agent.active ? "active" : "inactive"})`);
  }
  return lines.join("\n");
}

export function formatInboxItems(items: InboxItem[]): string {
  const lines = ["Inbox"];
  if (items.length === 0) {
    lines.push("  none");
    return lines.join("\n");
  }
  for (const item of items) {
    const taskSuffix = item.task_id ? ` task=${item.task_id}` : "";
    const agentSuffix = item.recipient_agent_id ? ` agent=${item.recipient_agent_id}` : "";
    lines.push(
      `  - ${item.id} [${item.kind}/${item.status}] project=${item.project_id}${taskSuffix}${agentSuffix} payload=${item.payload_ref.type}:${item.payload_ref.id}`,
    );
  }
  return lines.join("\n");
}

export function formatTaskMessages(messages: TaskMessage[]): string {
  const lines = ["Messages"];
  if (messages.length === 0) {
    lines.push("  none");
    return lines.join("\n");
  }
  for (const message of messages) {
    lines.push(
      `  - ${message.id} [${message.kind}] ${message.sender_worker_id}${message.sender_agent_id ? `/${message.sender_agent_id}` : ""} -> ${message.recipient_worker_id}${message.recipient_agent_id ? `/${message.recipient_agent_id}` : ""}: ${message.body}`,
    );
  }
  return lines.join("\n");
}

export function formatProjectBriefSchedule(schedule: ProjectBriefSchedule): string {
  return [
    `Project brief schedule: ${schedule.project_id}`,
    `Owner worker: ${schedule.owner_worker_id}`,
    `Timezone: ${schedule.timezone}`,
    `Delivery hour: ${schedule.delivery_hour_local}`,
    `Enabled: ${schedule.enabled ? "yes" : "no"}`,
    `Last run: ${schedule.last_run_at ?? "none"}`,
    `Next run: ${schedule.next_run_at ?? "none"}`,
  ].join("\n");
}
