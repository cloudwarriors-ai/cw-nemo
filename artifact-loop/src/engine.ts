// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ArtifactLoopEngine — file-persisted coordination engine.
 *
 * Storage layout:
 *   <dataDir>/tasks/<id>.json              → Task
 *   <dataDir>/projects/<id>.json           → Project
 *   <dataDir>/artifacts/<task-id>/<id>.json → NormalizedArtifact
 *   <dataDir>/state/<task-id>.json         → TaskState
 *   <dataDir>/derivations/<task-id>/<id>.json → DerivationRun
 */

import { mkdirSync, readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { derive } from "./derive.js";
import { createUsageStore, summarizeUsage } from "./usage-store.js";
import type {
  Assignment,
  AssignmentCreate,
  CanonicalStatus,
  DerivationOutput,
  DerivationRun,
  IngestResult,
  Organization,
  OrganizationBootstrapRequest,
  OrganizationBootstrapResult,
  NormalizedArtifact,
  NormalizationContext,
  Override,
  Project,
  ProjectBrief,
  ProjectBriefAttentionItem,
  ProjectBriefMovementItem,
  ProjectBriefRun,
  ProjectBriefSchedule,
  ProjectBriefScheduleUpsert,
  ProjectBriefWorkerGroup,
  ProjectAgentSummaryGroup,
  ProjectCreate,
  ProjectDefinition,
  ProjectHumanSummaryGroup,
  ProjectSummary,
  ProjectTaskLinkCreate,
  ProjectTaskListItem,
  ProjectWorkerSummary,
  RawArtifact,
  ScheduledBriefRunResult,
  SignalPayload,
  Task,
  TaskDraft,
  TaskDraftSet,
  TaskDraftSetApproveRequest,
  TaskDraftSetGenerateRequest,
  TaskDraftSetRejectRequest,
  TaskMessage,
  TaskMessageCreate,
  TaskCreate,
  Team,
  TeamCreate,
  TeamMembership,
  TeamMembershipCreate,
  TeamMembershipRole,
  TaskState,
  Worker,
  WorkerAgent,
  WorkerAgentCreate,
  WorkerCreate,
  InboxItem,
  InboxItemStatus,
} from "./types.js";

export interface EngineOptions {
  dataDir: string;
}

const DEFAULT_STATE: TaskState = {
  status: "not_started",
  task_confidence: 0,
  binding_confidence: 0,
  missing_inputs: [],
};

const CANONICAL_STATUSES: CanonicalStatus[] = [
  "not_started",
  "in_progress",
  "needs_input",
  "blocked",
  "ready_for_review",
  "done",
];

const BRIEF_MOVEMENT_LIMIT = 10;

interface ProjectTaskFilters {
  status?: CanonicalStatus;
  assignee_human_id?: string;
  assignee_agent_id?: string;
}

interface InboxFilters {
  status?: InboxItemStatus;
}

export class ArtifactLoopEngine {
  readonly dataDir: string;
  private readonly organizationPath: string;
  private readonly tasksDir: string;
  private readonly projectsDir: string;
  private readonly teamsDir: string;
  private readonly membershipsDir: string;
  private readonly draftSetsDir: string;
  private readonly workersDir: string;
  private readonly workerAgentsDir: string;
  private readonly inboxDir: string;
  private readonly messagesDir: string;
  private readonly briefSchedulesDir: string;
  private readonly briefRunsDir: string;
  private readonly artifactsDir: string;
  private readonly assignmentsDir: string;
  private readonly stateDir: string;
  private readonly derivationsDir: string;
  private readonly usageStore;

  constructor(options: EngineOptions) {
    this.dataDir = options.dataDir;
    this.organizationPath = join(options.dataDir, "organization.json");
    this.tasksDir = join(options.dataDir, "tasks");
    this.projectsDir = join(options.dataDir, "projects");
    this.teamsDir = join(options.dataDir, "teams");
    this.membershipsDir = join(options.dataDir, "team-memberships");
    this.draftSetsDir = join(options.dataDir, "task-draft-sets");
    this.workersDir = join(options.dataDir, "workers");
    this.workerAgentsDir = join(options.dataDir, "worker-agents");
    this.inboxDir = join(options.dataDir, "inbox");
    this.messagesDir = join(options.dataDir, "messages");
    this.briefSchedulesDir = join(options.dataDir, "brief-schedules");
    this.briefRunsDir = join(options.dataDir, "brief-runs");
    this.artifactsDir = join(options.dataDir, "artifacts");
    this.assignmentsDir = join(options.dataDir, "assignments");
    this.stateDir = join(options.dataDir, "state");
    this.derivationsDir = join(options.dataDir, "derivations");
    this.usageStore = createUsageStore(options.dataDir);

    mkdirSync(this.tasksDir, { recursive: true });
    mkdirSync(this.projectsDir, { recursive: true });
    mkdirSync(this.teamsDir, { recursive: true });
    mkdirSync(this.membershipsDir, { recursive: true });
    mkdirSync(this.draftSetsDir, { recursive: true });
    mkdirSync(this.workersDir, { recursive: true });
    mkdirSync(this.workerAgentsDir, { recursive: true });
    mkdirSync(this.inboxDir, { recursive: true });
    mkdirSync(this.messagesDir, { recursive: true });
    mkdirSync(this.briefSchedulesDir, { recursive: true });
    mkdirSync(this.briefRunsDir, { recursive: true });
    mkdirSync(this.artifactsDir, { recursive: true });
    mkdirSync(this.assignmentsDir, { recursive: true });
    mkdirSync(this.stateDir, { recursive: true });
    mkdirSync(this.derivationsDir, { recursive: true });
  }

  // ─── Task CRUD ────────────────────────────────────────────────────

  createTask(input: TaskCreate): Task {
    const existing = this.getTask(input.id);
    if (existing) {
      throw new Error(`Task already exists: ${input.id}`);
    }

    const task: Task = {
      ...input,
      last_activity_at: new Date().toISOString(),
    };

    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);
    this.writeJson(join(this.stateDir, `${task.id}.json`), {
      ...DEFAULT_STATE,
      status: input.status,
    });

    return task;
  }

  bootstrapOrganization(input: OrganizationBootstrapRequest): OrganizationBootstrapResult {
    if (this.getOrganization()) {
      throw new Error("Organization already exists");
    }

    const now = new Date().toISOString();
    const organization: Organization = {
      id: input.organization.id,
      name: input.organization.name,
      timezone: input.organization.timezone,
      created_at: now,
      updated_at: now,
    };
    this.writeJson(this.organizationPath, organization);

    const member = this.createWorker({
      id: input.initial_member.id,
      display_name: input.initial_member.display_name,
      role: "admin",
      timezone: input.initial_member.timezone,
      active: true,
    });

    const team: Team = {
      id: input.initial_team.id,
      organization_id: organization.id,
      name: input.initial_team.name,
      description: input.initial_team.description,
      created_at: now,
      updated_at: now,
    };
    this.writeJson(join(this.teamsDir, `${team.id}.json`), team);

    const membership: TeamMembership = {
      member_id: member.id,
      team_id: team.id,
      role: "admin",
      status: "active",
      created_at: now,
      updated_at: now,
    };
    this.writeJson(this.membershipPath(team.id, member.id), membership);

    const agent = this.createWorkerAgent(member.id, input.initial_agent);
    return { organization, team, membership, member, agent };
  }

  getOrganization(): Organization | undefined {
    return this.readJson<Organization>(this.organizationPath);
  }

  createTeam(input: TeamCreate): Team {
    const organization = this.getOrganization();
    if (!organization) {
      throw new Error("Organization not bootstrapped");
    }
    if (this.getTeam(input.id)) {
      throw new Error(`Team already exists: ${input.id}`);
    }
    if (!this.getWorker(input.created_by_worker_id)) {
      throw new Error(`Worker not found: ${input.created_by_worker_id}`);
    }
    this.assertMemberHasRole(input.created_by_worker_id, undefined, ["admin"]);

    const now = new Date().toISOString();
    const team: Team = {
      id: input.id,
      organization_id: organization.id,
      name: input.name,
      description: input.description,
      created_at: now,
      updated_at: now,
    };
    this.writeJson(join(this.teamsDir, `${team.id}.json`), team);
    return team;
  }

  getTeam(teamId: string): Team | undefined {
    return this.readJson<Team>(join(this.teamsDir, `${teamId}.json`));
  }

  getTeams(): Team[] {
    return readdirSync(this.teamsDir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<Team>(join(this.teamsDir, f))!)
      .filter(Boolean)
      .sort((a, b) => a.id.localeCompare(b.id));
  }

  addTeamMember(teamId: string, input: TeamMembershipCreate): TeamMembership {
    const team = this.getTeam(teamId);
    if (!team) {
      throw new Error(`Team not found: ${teamId}`);
    }
    if (!this.getWorker(input.added_by_worker_id)) {
      throw new Error(`Worker not found: ${input.added_by_worker_id}`);
    }
    this.assertMemberHasRole(input.added_by_worker_id, undefined, ["admin"]);

    let worker = this.getWorker(input.member_id);
    if (!worker) {
      if (!input.display_name || !input.timezone) {
        throw new Error(`Worker not found: ${input.member_id}`);
      }
      worker = this.createWorker({
        id: input.member_id,
        display_name: input.display_name,
        role: input.worker_role ?? input.role,
        timezone: input.timezone,
        active: input.status !== "inactive",
      });
    }

    const otherMemberships = this.getMembershipsForMember(input.member_id)
      .filter((membership) => membership.team_id !== teamId);
    if (otherMemberships.length > 0) {
      throw new Error(`Member already belongs to different team: ${input.member_id}`);
    }

    const existing = this.getTeamMembership(teamId, input.member_id);
    const now = new Date().toISOString();
    const membership: TeamMembership = existing
      ? {
          ...existing,
          role: input.role,
          status: input.status ?? existing.status,
          updated_at: now,
        }
      : {
          member_id: input.member_id,
          team_id: teamId,
          role: input.role,
          status: input.status ?? "active",
          created_at: now,
          updated_at: now,
        };

    this.writeJson(this.membershipPath(teamId, input.member_id), membership);
    return membership;
  }

  getTeamMembership(teamId: string, memberId: string): TeamMembership | undefined {
    return this.readJson<TeamMembership>(this.membershipPath(teamId, memberId));
  }

  getMembershipsForMember(memberId: string): TeamMembership[] {
    return readdirSync(this.membershipsDir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<TeamMembership>(join(this.membershipsDir, f))!)
      .filter((membership) => membership?.member_id === memberId)
      .sort((a, b) => a.team_id.localeCompare(b.team_id));
  }

  getTeamMembers(teamId: string): TeamMembership[] {
    const team = this.getTeam(teamId);
    if (!team) {
      throw new Error(`Team not found: ${teamId}`);
    }

    return readdirSync(this.membershipsDir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<TeamMembership>(join(this.membershipsDir, f))!)
      .filter((membership) => membership?.team_id === teamId)
      .sort((a, b) => a.member_id.localeCompare(b.member_id));
  }

  createWorker(input: WorkerCreate): Worker {
    const existing = this.getWorker(input.id);
    if (existing) {
      throw new Error(`Worker already exists: ${input.id}`);
    }

    const now = new Date().toISOString();
    const worker: Worker = {
      id: input.id,
      display_name: input.display_name,
      role: input.role,
      timezone: input.timezone,
      active: input.active ?? true,
      created_at: now,
      updated_at: now,
    };

    this.writeJson(join(this.workersDir, `${worker.id}.json`), worker);
    return worker;
  }

  getWorker(workerId: string): Worker | undefined {
    return this.readJson<Worker>(join(this.workersDir, `${workerId}.json`));
  }

  getWorkers(): Worker[] {
    return readdirSync(this.workersDir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<Worker>(join(this.workersDir, f))!)
      .filter(Boolean)
      .sort((a, b) => a.id.localeCompare(b.id));
  }

  createWorkerAgent(workerId: string, input: WorkerAgentCreate): WorkerAgent {
    const worker = this.getWorker(workerId);
    if (!worker) {
      throw new Error(`Worker not found: ${workerId}`);
    }

    const existing = this.getWorkerAgent(input.id);
    if (existing) {
      throw new Error(`Worker agent already exists: ${input.id}`);
    }

    const now = new Date().toISOString();
    const agent: WorkerAgent = {
      id: input.id,
      worker_id: workerId,
      label: input.label,
      connector_type: input.connector_type,
      active: input.active ?? true,
      created_at: now,
      updated_at: now,
    };

    this.writeJson(join(this.workerAgentsDir, `${agent.id}.json`), agent);
    return agent;
  }

  getWorkerAgent(agentId: string): WorkerAgent | undefined {
    return this.readJson<WorkerAgent>(join(this.workerAgentsDir, `${agentId}.json`));
  }

  getWorkerAgents(workerId: string): WorkerAgent[] {
    const worker = this.getWorker(workerId);
    if (!worker) {
      throw new Error(`Worker not found: ${workerId}`);
    }

    return readdirSync(this.workerAgentsDir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<WorkerAgent>(join(this.workerAgentsDir, f))!)
      .filter((agent) => agent?.worker_id === workerId)
      .sort((a, b) => a.id.localeCompare(b.id));
  }

  createProject(input: ProjectCreate): Project {
    const existing = this.getProject(input.id);
    if (existing) {
      throw new Error(`Project already exists: ${input.id}`);
    }

    const team = this.getTeam(input.team_id);
    if (!team) {
      throw new Error(`Team not found: ${input.team_id}`);
    }

    if (!this.getWorker(input.owner_worker_id)) {
      throw new Error(`Worker not found: ${input.owner_worker_id}`);
    }
    this.assertMemberHasRole(input.owner_worker_id, team.id, ["admin", "lead"]);

    const now = new Date().toISOString();
    const project: Project = {
      ...input,
      created_at: now,
      updated_at: now,
    };
    this.writeJson(join(this.projectsDir, `${project.id}.json`), project);
    return project;
  }

  getProject(projectId: string): Project | undefined {
    return this.readJson<Project>(join(this.projectsDir, `${projectId}.json`));
  }

  getProjects(): Project[] {
    return readdirSync(this.projectsDir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<Project>(join(this.projectsDir, f))!)
      .filter(Boolean)
      .sort((a, b) => a.id.localeCompare(b.id));
  }

  createTaskDraftSet(projectId: string, input: TaskDraftSetGenerateRequest): TaskDraftSet {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }
    if (!this.getWorkerAgent(input.generated_by_agent_id)) {
      throw new Error(`Worker agent not found: ${input.generated_by_agent_id}`);
    }

    const draftIds = new Set<string>();
    for (const draft of input.drafts) {
      if (draftIds.has(draft.id)) {
        throw new Error(`Duplicate task draft id: ${draft.id}`);
      }
      draftIds.add(draft.id);
    }

    const now = new Date().toISOString();
    const draftSet: TaskDraftSet = {
      id: `draft-set-${randomUUID()}`,
      project_id: projectId,
      status: "draft",
      generated_by_agent_id: input.generated_by_agent_id,
      generated_at: now,
      drafts: input.drafts,
    };

    const dir = join(this.draftSetsDir, projectId);
    mkdirSync(dir, { recursive: true });
    this.writeJson(join(dir, `${draftSet.id}.json`), draftSet);
    return draftSet;
  }

  getTaskDraftSets(projectId: string): TaskDraftSet[] {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }

    const dir = join(this.draftSetsDir, projectId);
    if (!existsSync(dir)) return [];

    return readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<TaskDraftSet>(join(dir, f))!)
      .filter(Boolean)
      .sort((a, b) => a.generated_at.localeCompare(b.generated_at));
  }

  getTaskDraftSet(projectId: string, draftSetId: string): TaskDraftSet | undefined {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }
    return this.readJson<TaskDraftSet>(join(this.draftSetsDir, projectId, `${draftSetId}.json`));
  }

  approveTaskDraftSet(
    projectId: string,
    draftSetId: string,
    input: TaskDraftSetApproveRequest,
  ): { draftSet: TaskDraftSet; tasks: Task[] } {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }
    if (!this.getWorker(input.approved_by_worker_id)) {
      throw new Error(`Worker not found: ${input.approved_by_worker_id}`);
    }
    this.assertMemberHasRole(input.approved_by_worker_id, project.team_id, ["admin", "lead"]);

    const draftSet = this.getTaskDraftSet(projectId, draftSetId);
    if (!draftSet) {
      throw new Error(`Task draft set not found: ${draftSetId}`);
    }
    if (draftSet.status !== "draft") {
      throw new Error(`Task draft set is not approvable: ${draftSetId}`);
    }

    for (const draft of draftSet.drafts) {
      if (this.getTask(draft.id)) {
        throw new Error(`Task already exists: ${draft.id}`);
      }
    }

    const tasks = draftSet.drafts.map((draft) =>
      this.createTask({
        id: draft.id,
        title: draft.title,
        description: draft.description,
        assignee_human_id: project.owner_worker_id ?? input.approved_by_worker_id,
        status: "not_started",
        acceptance_criteria: draft.acceptance_criteria,
        acceptance_signals: draft.acceptance_signals,
        depends_on: draft.depends_on_draft_ids,
      }),
    ).map((task) => this.assignTaskToProject(projectId, task.id));

    draftSet.status = "approved";
    draftSet.approved_at = new Date().toISOString();
    draftSet.approved_by_worker_id = input.approved_by_worker_id;
    this.writeJson(join(this.draftSetsDir, projectId, `${draftSet.id}.json`), draftSet);

    return { draftSet, tasks };
  }

  rejectTaskDraftSet(projectId: string, draftSetId: string, input: TaskDraftSetRejectRequest): TaskDraftSet {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }
    if (!this.getWorker(input.rejected_by_worker_id)) {
      throw new Error(`Worker not found: ${input.rejected_by_worker_id}`);
    }

    const draftSet = this.getTaskDraftSet(projectId, draftSetId);
    if (!draftSet) {
      throw new Error(`Task draft set not found: ${draftSetId}`);
    }
    if (draftSet.status !== "draft") {
      throw new Error(`Task draft set is not rejectable: ${draftSetId}`);
    }

    draftSet.status = "rejected";
    draftSet.rejected_at = new Date().toISOString();
    draftSet.rejected_by_worker_id = input.rejected_by_worker_id;
    this.writeJson(join(this.draftSetsDir, projectId, `${draftSet.id}.json`), draftSet);
    return draftSet;
  }

  getTask(taskId: string): Task | undefined {
    return this.readJson<Task>(join(this.tasksDir, `${taskId}.json`));
  }

  getTasks(): Task[] {
    return readdirSync(this.tasksDir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<Task>(join(this.tasksDir, f))!)
      .filter(Boolean)
      .sort((a, b) => a.id.localeCompare(b.id));
  }

  assignTaskToProject(projectId: string, taskId: string): Task {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }

    const task = this.getTask(taskId);
    if (!task) {
      throw new Error(`Task not found: ${taskId}`);
    }

    if (task.project_id && task.project_id !== projectId) {
      throw new Error(`Task already linked to different project: ${taskId} -> ${task.project_id}`);
    }

    if (task.project_id === projectId) {
      return task;
    }

    const now = new Date().toISOString();
    task.project_id = projectId;
    task.last_activity_at = now;
    project.updated_at = now;

    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);
    this.writeJson(join(this.projectsDir, `${project.id}.json`), project);
    return task;
  }

  getProjectTasks(projectId: string, filters: ProjectTaskFilters = {}): Task[] {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }

    return this.getTasks()
      .filter((task) => task.project_id === projectId)
      .filter((task) => {
        if (filters.assignee_human_id && task.assignee_human_id !== filters.assignee_human_id) {
          return false;
        }
        if (filters.assignee_agent_id && task.assignee_agent_id !== filters.assignee_agent_id) {
          return false;
        }
        if (filters.status) {
          return this.resolveTaskStatus(task) === filters.status;
        }
        return true;
      });
  }

  getProjectSummary(projectId: string): ProjectSummary {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }

    const tasks = this.getProjectTasks(projectId);
    const counts_by_status = Object.fromEntries(
      CANONICAL_STATUSES.map((status) => [status, 0]),
    ) as Record<CanonicalStatus, number>;
    const buckets: ProjectSummary["buckets"] = {
      blocked: [],
      needs_input: [],
      ready_for_review: [],
    };

    let last_activity_at: string | null = null;
    for (const task of tasks) {
      const status = this.resolveTaskStatus(task);
      counts_by_status[status] += 1;
      const item = this.toProjectTaskListItem(task, status);

      if (status === "blocked") buckets.blocked.push(item);
      if (status === "needs_input") buckets.needs_input.push(item);
      if (status === "ready_for_review") buckets.ready_for_review.push(item);
      if (!last_activity_at || task.last_activity_at > last_activity_at) {
        last_activity_at = task.last_activity_at;
      }
    }

    this.sortProjectTaskItems(buckets.blocked);
    this.sortProjectTaskItems(buckets.needs_input);
    this.sortProjectTaskItems(buckets.ready_for_review);

    return {
      project,
      total_tasks: tasks.length,
      counts_by_status,
      buckets,
      last_activity_at,
    };
  }

  getProjectWorkerSummary(projectId: string): ProjectWorkerSummary {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }

    const tasks = this.getProjectTasks(projectId);
    const byHuman = new Map<string, ProjectTaskListItem[]>();
    const byAgent = new Map<string, ProjectTaskListItem[]>();

    for (const task of tasks) {
      const item = this.toProjectTaskListItem(task, this.resolveTaskStatus(task));
      const humanTasks = byHuman.get(task.assignee_human_id) ?? [];
      humanTasks.push(item);
      byHuman.set(task.assignee_human_id, humanTasks);

      if (task.assignee_agent_id) {
        const agentTasks = byAgent.get(task.assignee_agent_id) ?? [];
        agentTasks.push(item);
        byAgent.set(task.assignee_agent_id, agentTasks);
      }
    }

    const normalizeGroupTasks = <T extends ProjectHumanSummaryGroup | ProjectAgentSummaryGroup>(
      groups: T[],
    ): T[] => groups.map((group) => ({
      ...group,
      tasks: this.sortProjectTaskItems([...group.tasks]),
    }));

    return {
      project_id: project.id,
      by_human: normalizeGroupTasks(
        [...byHuman.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([assignee_human_id, groupTasks]) => ({
            assignee_human_id,
            tasks: groupTasks,
          })),
      ),
      by_agent: normalizeGroupTasks(
        [...byAgent.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([assignee_agent_id, groupTasks]) => ({
            assignee_agent_id,
            tasks: groupTasks,
          })),
      ),
    };
  }

  getProjectBrief(projectId: string): ProjectBrief {
    return this.buildProjectBrief(projectId);
  }

  // ─── Assignments ──────────────────────────────────────────────────

  createAssignment(taskId: string, input: AssignmentCreate): Assignment {
    const task = this.getTask(taskId);
    if (!task) {
      throw new Error(`Task not found: ${taskId}`);
    }
    const assignee = this.getWorker(input.assignee_human_id);
    if (!assignee) {
      throw new Error(`Worker not found: ${input.assignee_human_id}`);
    }
    if (input.assignee_agent_id) {
      const agent = this.getWorkerAgent(input.assignee_agent_id);
      if (!agent) {
        throw new Error(`Worker agent not found: ${input.assignee_agent_id}`);
      }
      if (agent.worker_id !== input.assignee_human_id) {
        throw new Error(`Worker agent ${input.assignee_agent_id} does not belong to worker ${input.assignee_human_id}`);
      }
    }
    if (input.assigned_by && !this.getWorker(input.assigned_by)) {
      throw new Error(`Worker not found: ${input.assigned_by}`);
    }
    if (task.project_id) {
      const project = this.getProject(task.project_id);
      if (!project) {
        throw new Error(`Project not found: ${task.project_id}`);
      }
      this.assertActiveTeamMembership(input.assignee_human_id, project.team_id, ["worker"]);
      if (!input.assigned_by) {
        throw new Error(`Team-scoped assignment requires assigned_by: ${taskId}`);
      }
      this.assertMemberHasRole(input.assigned_by, project.team_id, ["admin", "lead"]);
    }

    const priorAssignments = this.getAssignments(taskId);
    const latestAssignedAt = priorAssignments.at(-1)?.assigned_at;
    let assignedAt = new Date().toISOString();
    if (latestAssignedAt && Date.parse(assignedAt) <= Date.parse(latestAssignedAt)) {
      assignedAt = new Date(Date.parse(latestAssignedAt) + 1).toISOString();
    }

    const assignment: Assignment = {
      id: `assign-${randomUUID()}`,
      task_id: taskId,
      assignee_human_id: input.assignee_human_id,
      assignee_agent_id: input.assignee_agent_id,
      assigned_at: assignedAt,
      assigned_by: input.assigned_by,
    };

    const assignmentDir = join(this.assignmentsDir, taskId);
    mkdirSync(assignmentDir, { recursive: true });
    this.writeJson(join(assignmentDir, `${assignment.id}.json`), assignment);

    task.assignee_human_id = assignment.assignee_human_id;
    if (assignment.assignee_agent_id) {
      task.assignee_agent_id = assignment.assignee_agent_id;
    } else {
      delete task.assignee_agent_id;
    }
    task.last_activity_at = assignment.assigned_at;
    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);

    const pendingKinds: Array<"assignment" | "reassignment"> = ["assignment", "reassignment"];
    const priorPendingInbox = this.getInboxItems({
      task_id: taskId,
      statuses: ["pending"],
    }).filter((item) => item.kind === "assignment" || item.kind === "reassignment");
    for (const inboxItem of priorPendingInbox) {
      this.updateInboxItem(inboxItem.id, {
        status: "superseded",
      });
    }

    if (assignment.assignee_agent_id && task.project_id) {
      this.createInboxItem({
        recipient_worker_id: assignment.assignee_human_id,
        recipient_agent_id: assignment.assignee_agent_id,
        project_id: task.project_id,
        task_id: taskId,
        kind: priorAssignments.length === 0 ? "assignment" : "reassignment",
        payload_ref: { type: "assignment", id: assignment.id },
      }, assignment.assigned_at);
    }

    return assignment;
  }

  getAssignments(taskId: string): Assignment[] {
    const dir = join(this.assignmentsDir, taskId);
    if (!existsSync(dir)) return [];

    return readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<Assignment>(join(dir, f))!)
      .filter(Boolean)
      .sort((a, b) => a.assigned_at.localeCompare(b.assigned_at));
  }

  getInboxItems(filters: {
    recipient_agent_id?: string;
    recipient_worker_id?: string;
    task_id?: string;
    statuses?: InboxItemStatus[];
  } = {}): InboxItem[] {
    return readdirSync(this.inboxDir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<InboxItem>(join(this.inboxDir, f))!)
      .filter(Boolean)
      .filter((item) => {
        if (filters.recipient_agent_id && item.recipient_agent_id !== filters.recipient_agent_id) return false;
        if (filters.recipient_worker_id && item.recipient_worker_id !== filters.recipient_worker_id) return false;
        if (filters.task_id && item.task_id !== filters.task_id) return false;
        if (filters.statuses && !filters.statuses.includes(item.status)) return false;
        return true;
      })
      .sort((a, b) => {
        if (a.created_at === b.created_at) return a.id.localeCompare(b.id);
        return b.created_at.localeCompare(a.created_at);
      });
  }

  getWorkerAgentInbox(agentId: string, filters: InboxFilters = {}): InboxItem[] {
    const agent = this.getWorkerAgent(agentId);
    if (!agent) {
      throw new Error(`Worker agent not found: ${agentId}`);
    }

    const statuses = filters.status ? [filters.status] : undefined;
    return this.getInboxItems({ recipient_agent_id: agentId, statuses });
  }

  acknowledgeInboxItem(inboxItemId: string): InboxItem {
    const item = this.readJson<InboxItem>(join(this.inboxDir, `${inboxItemId}.json`));
    if (!item) {
      throw new Error(`Inbox item not found: ${inboxItemId}`);
    }

    if (item.status !== "pending") {
      return item;
    }

    item.status = "acknowledged";
    item.acknowledged_at = new Date().toISOString();
    this.writeJson(join(this.inboxDir, `${item.id}.json`), item);
    return item;
  }

  createTaskMessage(taskId: string, input: TaskMessageCreate): TaskMessage {
    const task = this.getTask(taskId);
    if (!task) {
      throw new Error(`Task not found: ${taskId}`);
    }
    if (!task.project_id) {
      throw new Error(`Task is not linked to a project: ${taskId}`);
    }
    const project = this.getProject(task.project_id);
    if (!project) {
      throw new Error(`Project not found: ${task.project_id}`);
    }
    if (!this.getWorker(input.sender_worker_id)) {
      throw new Error(`Worker not found: ${input.sender_worker_id}`);
    }
    if (!this.getWorker(input.recipient_worker_id)) {
      throw new Error(`Worker not found: ${input.recipient_worker_id}`);
    }
    if (input.sender_agent_id) {
      const senderAgent = this.getWorkerAgent(input.sender_agent_id);
      if (!senderAgent) {
        throw new Error(`Worker agent not found: ${input.sender_agent_id}`);
      }
      if (senderAgent.worker_id !== input.sender_worker_id) {
        throw new Error(`Worker agent ${input.sender_agent_id} does not belong to worker ${input.sender_worker_id}`);
      }
    }
    if (input.recipient_agent_id) {
      const recipientAgent = this.getWorkerAgent(input.recipient_agent_id);
      if (!recipientAgent) {
        throw new Error(`Worker agent not found: ${input.recipient_agent_id}`);
      }
      if (recipientAgent.worker_id !== input.recipient_worker_id) {
        throw new Error(`Worker agent ${input.recipient_agent_id} does not belong to worker ${input.recipient_worker_id}`);
      }
    }
    this.assertActiveTeamMembership(input.sender_worker_id, project.team_id);
    this.assertActiveTeamMembership(input.recipient_worker_id, project.team_id);

    const createdAt = new Date().toISOString();
    const message: TaskMessage = {
      id: `msg-${randomUUID()}`,
      project_id: project.id,
      task_id: taskId,
      sender_worker_id: input.sender_worker_id,
      sender_agent_id: input.sender_agent_id,
      recipient_worker_id: input.recipient_worker_id,
      recipient_agent_id: input.recipient_agent_id,
      kind: input.kind,
      body: input.body,
      created_at: createdAt,
    };

    const dir = join(this.messagesDir, taskId);
    mkdirSync(dir, { recursive: true });
    this.writeJson(join(dir, `${message.id}.json`), message);
    task.last_activity_at = createdAt;
    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);

    if (message.recipient_agent_id) {
      this.createInboxItem({
        recipient_worker_id: message.recipient_worker_id,
        recipient_agent_id: message.recipient_agent_id,
        project_id: message.project_id,
        task_id: taskId,
        kind: "message",
        payload_ref: { type: "message", id: message.id },
      }, createdAt);
    }

    return message;
  }

  getTaskMessages(taskId: string): TaskMessage[] {
    const task = this.getTask(taskId);
    if (!task) {
      throw new Error(`Task not found: ${taskId}`);
    }

    const dir = join(this.messagesDir, taskId);
    if (!existsSync(dir)) return [];

    return readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<TaskMessage>(join(dir, f))!)
      .filter(Boolean)
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
  }

  acknowledgeTaskMessage(messageId: string): TaskMessage {
    for (const dirEntry of readdirSync(this.messagesDir)) {
      const messagePath = join(this.messagesDir, dirEntry, `${messageId}.json`);
      const message = this.readJson<TaskMessage>(messagePath);
      if (!message) continue;

      if (!message.acknowledged_at) {
        message.acknowledged_at = new Date().toISOString();
        this.writeJson(messagePath, message);
      }

      for (const inboxItem of this.getInboxItems({ task_id: message.task_id })) {
        if (inboxItem.payload_ref.type === "message" && inboxItem.payload_ref.id === message.id) {
          this.acknowledgeInboxItem(inboxItem.id);
        }
      }
      return message;
    }

    throw new Error(`Message not found: ${messageId}`);
  }

  upsertProjectBriefSchedule(projectId: string, input: ProjectBriefScheduleUpsert): ProjectBriefSchedule {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }
    if (!this.getWorker(input.owner_worker_id)) {
      throw new Error(`Worker not found: ${input.owner_worker_id}`);
    }
    this.assertMemberHasRole(input.owner_worker_id, project.team_id, ["admin", "lead"]);
    if (input.delivery_hour_local < 0 || input.delivery_hour_local > 23) {
      throw new Error(`Invalid delivery hour: ${String(input.delivery_hour_local)}`);
    }

    const existing = this.getProjectBriefSchedule(projectId);
    const now = new Date();
    const schedule: ProjectBriefSchedule = {
      project_id: projectId,
      owner_worker_id: input.owner_worker_id,
      timezone: input.timezone,
      delivery_hour_local: input.delivery_hour_local,
      enabled: input.enabled,
      last_run_at: existing?.last_run_at,
      next_run_at: input.enabled
        ? this.computeNextRunAt(input.timezone, input.delivery_hour_local, existing?.last_run_at ? new Date(existing.last_run_at) : now)
        : undefined,
    };

    this.writeJson(join(this.briefSchedulesDir, `${projectId}.json`), schedule);
    return schedule;
  }

  getProjectBriefSchedule(projectId: string): ProjectBriefSchedule | undefined {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }
    return this.readJson<ProjectBriefSchedule>(join(this.briefSchedulesDir, `${projectId}.json`));
  }

  getProjectBriefRuns(projectId: string): ProjectBriefRun[] {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }
    const dir = join(this.briefRunsDir, projectId);
    if (!existsSync(dir)) return [];
    return readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<ProjectBriefRun>(join(dir, f))!)
      .filter(Boolean)
      .sort((a, b) => a.generated_at.localeCompare(b.generated_at));
  }

  getProjectBriefRun(projectId: string, briefRunId: string): ProjectBriefRun | undefined {
    const project = this.getProject(projectId);
    if (!project) {
      throw new Error(`Project not found: ${projectId}`);
    }
    return this.readJson<ProjectBriefRun>(join(this.briefRunsDir, projectId, `${briefRunId}.json`));
  }

  getLatestProjectBriefRun(projectId: string): ProjectBriefRun | undefined {
    return this.getProjectBriefRuns(projectId).at(-1);
  }

  runScheduledBriefs(now = new Date()): ScheduledBriefRunResult {
    const schedules = readdirSync(this.briefSchedulesDir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<ProjectBriefSchedule>(join(this.briefSchedulesDir, f))!)
      .filter(Boolean);

    const generated: string[] = [];
    for (const schedule of schedules) {
      if (!schedule.enabled || !schedule.next_run_at) continue;
      if (schedule.next_run_at > now.toISOString()) continue;

      const previousRun = this.getLatestProjectBriefRun(schedule.project_id);
      const window_start = previousRun?.generated_at ?? this.getProject(schedule.project_id)?.created_at ?? now.toISOString();
      const window_end = now.toISOString();
      const brief = this.buildProjectBrief(schedule.project_id, {
        movementWindowStart: window_start,
        movementWindowEnd: window_end,
      });
      const briefRun: ProjectBriefRun = {
        id: `brief-run-${randomUUID()}`,
        project_id: schedule.project_id,
        generated_at: window_end,
        window_start,
        window_end,
        brief,
      };

      const runDir = join(this.briefRunsDir, schedule.project_id);
      mkdirSync(runDir, { recursive: true });
      this.writeJson(join(runDir, `${briefRun.id}.json`), briefRun);

      schedule.last_run_at = window_end;
      schedule.next_run_at = this.computeNextRunAt(schedule.timezone, schedule.delivery_hour_local, now);
      this.writeJson(join(this.briefSchedulesDir, `${schedule.project_id}.json`), schedule);

      this.createInboxItem({
        recipient_worker_id: schedule.owner_worker_id,
        project_id: schedule.project_id,
        kind: "brief",
        payload_ref: { type: "brief_run", id: briefRun.id },
      }, window_end);
      generated.push(schedule.project_id);
    }

    return {
      generated_count: generated.length,
      generated_project_ids: generated,
    };
  }

  // ─── State ────────────────────────────────────────────────────────

  getTaskState(taskId: string): TaskState | undefined {
    return this.readJson<TaskState>(join(this.stateDir, `${taskId}.json`));
  }

  // ─── Artifacts ────────────────────────────────────────────────────

  getArtifacts(taskId: string): NormalizedArtifact[] {
    const dir = join(this.artifactsDir, taskId);
    if (!existsSync(dir)) return [];

    return readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<NormalizedArtifact>(join(dir, f))!)
      .filter(Boolean);
  }

  // ─── Derivation History ───────────────────────────────────────────

  getDerivationHistory(taskId: string): DerivationRun[] {
    const dir = join(this.derivationsDir, taskId);
    if (!existsSync(dir)) return [];

    return readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<DerivationRun>(join(dir, f))!)
      .filter(Boolean)
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }

  getUsageStats() {
    return summarizeUsage(
      this.usageStore.list(),
      this.getTasks(),
      (taskId) => this.getArtifacts(taskId),
    );
  }

  // ─── Ingest ───────────────────────────────────────────────────────

  ingest(rawArtifact: RawArtifact, context: NormalizationContext): IngestResult {
    const task = this.getTask(context.primary_task_id);
    if (!task) {
      throw new Error(`Task not found: ${context.primary_task_id}`);
    }

    // Normalize raw artifact
    const normalizedArtifact: NormalizedArtifact = {
      id: `na-${rawArtifact.id}`,
      raw_artifact_id: rawArtifact.id,
      primary_task_id: context.primary_task_id,
      session_id: context.session_id,
      artifact_source: rawArtifact.source,
      worker_id: context.worker_id,
      worker_agent_id: context.worker_agent_id,
      context_source: context.context_source,
      timestamp: rawArtifact.timestamp,
      normalization_state: "normalized",
      binding_confidence:
        context.context_source === "explicit_lock" || context.context_source === "session_default"
          ? 1.0
          : 0.7,
      signal_payload: rawArtifact.raw_payload as SignalPayload,
    };

    // Store artifact
    const artifactDir = join(this.artifactsDir, context.primary_task_id);
    mkdirSync(artifactDir, { recursive: true });
    this.writeJson(join(artifactDir, `${normalizedArtifact.id}.json`), normalizedArtifact);

    // Load all artifacts for derivation
    const allArtifacts = this.getArtifacts(context.primary_task_id);
    const priorState = this.getTaskState(context.primary_task_id) ?? { ...DEFAULT_STATE };

    // Derive
    const derivationOutput = derive({
      priorState,
      normalizedArtifacts: allArtifacts,
      acceptanceSignals: task.acceptance_signals,
      override: task.override
        ? { id: `override-${task.id}`, ...task.override }
        : undefined,
    });

    // Fill task_id on derivation run
    if (derivationOutput.derivationRun) {
      derivationOutput.derivationRun.task_id = context.primary_task_id;
    }

    // Persist state
    this.writeJson(
      join(this.stateDir, `${context.primary_task_id}.json`),
      derivationOutput.nextState,
    );

    // Persist derivation run
    if (derivationOutput.derivationRun) {
      const runDir = join(this.derivationsDir, context.primary_task_id);
      mkdirSync(runDir, { recursive: true });
      this.writeJson(
        join(runDir, `${derivationOutput.derivationRun.id}.json`),
        derivationOutput.derivationRun,
      );
    }

    // Update task activity
    task.last_activity_at = rawArtifact.timestamp;
    task.status = derivationOutput.nextState.status;
    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);

    return { normalizedArtifact, derivationOutput };
  }

  // ─── Override ─────────────────────────────────────────────────────

  applyOverride(taskId: string, override: Override): DerivationOutput {
    const task = this.getTask(taskId);
    if (!task) {
      throw new Error(`Task not found: ${taskId}`);
    }

    // Store override on task
    task.override = override;
    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);

    // Run derivation with override
    const allArtifacts = this.getArtifacts(taskId);
    const priorState = this.getTaskState(taskId) ?? { ...DEFAULT_STATE };

    const overrideRecord = {
      id: `override-${taskId}-${Date.now()}`,
      ...override,
    };

    const derivationOutput = derive({
      priorState,
      normalizedArtifacts: allArtifacts,
      acceptanceSignals: task.acceptance_signals,
      override: overrideRecord,
    });

    // Fill task_id
    if (derivationOutput.derivationRun) {
      derivationOutput.derivationRun.task_id = taskId;
    }

    // Persist state
    this.writeJson(join(this.stateDir, `${taskId}.json`), derivationOutput.nextState);

    // Persist derivation run
    if (derivationOutput.derivationRun) {
      const runDir = join(this.derivationsDir, taskId);
      mkdirSync(runDir, { recursive: true });
      this.writeJson(
        join(runDir, `${derivationOutput.derivationRun.id}.json`),
        derivationOutput.derivationRun,
      );
    }

    // Update task status
    task.status = derivationOutput.nextState.status;
    task.last_activity_at = override.timestamp;
    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);
    this.usageStore.append({
      kind: "override_applied",
      timestamp: override.timestamp,
      task_id: taskId,
      resulting_status: derivationOutput.nextState.status,
    });

    return derivationOutput;
  }

  private membershipPath(teamId: string, memberId: string): string {
    return join(this.membershipsDir, `${teamId}__${memberId}.json`);
  }

  private assertMemberHasRole(
    memberId: string,
    teamId: string | undefined,
    roles: TeamMembershipRole[],
  ): TeamMembership {
    const memberships = teamId
      ? [this.getTeamMembership(teamId, memberId)].filter(Boolean) as TeamMembership[]
      : this.getMembershipsForMember(memberId);
    const membership = memberships.find((candidate) =>
      candidate.status === "active" && roles.includes(candidate.role),
    );
    if (membership) {
      return membership;
    }

    if (teamId) {
      throw new Error(`Member lacks required team role: ${memberId} in ${teamId}`);
    }
    throw new Error(`Member lacks required org role: ${memberId}`);
  }

  private assertActiveTeamMembership(
    memberId: string,
    teamId: string | undefined,
    roles?: TeamMembershipRole[],
  ): TeamMembership | undefined {
    if (!teamId) return undefined;
    const membership = this.getTeamMembership(teamId, memberId);
    if (!membership || membership.status !== "active") {
      throw new Error(`Member is not active in team: ${memberId} in ${teamId}`);
    }
    if (roles && !roles.includes(membership.role)) {
      throw new Error(`Member lacks required team role: ${memberId} in ${teamId}`);
    }
    return membership;
  }

  // ─── File I/O ─────────────────────────────────────────────────────

  private writeJson(path: string, data: unknown): void {
    writeFileSync(path, JSON.stringify(data, null, 2) + "\n", "utf-8");
  }

  private createInboxItem(
    input: Omit<InboxItem, "id" | "status" | "created_at" | "acknowledged_at">,
    createdAt = new Date().toISOString(),
  ): InboxItem {
    const item: InboxItem = {
      id: `inbox-${randomUUID()}`,
      ...input,
      status: "pending",
      created_at: createdAt,
    };
    this.writeJson(join(this.inboxDir, `${item.id}.json`), item);
    return item;
  }

  private updateInboxItem(inboxItemId: string, patch: Partial<InboxItem>): InboxItem {
    const item = this.readJson<InboxItem>(join(this.inboxDir, `${inboxItemId}.json`));
    if (!item) {
      throw new Error(`Inbox item not found: ${inboxItemId}`);
    }

    const updated: InboxItem = { ...item, ...patch };
    this.writeJson(join(this.inboxDir, `${updated.id}.json`), updated);
    return updated;
  }

  private buildProjectBrief(
    projectId: string,
    options: {
      movementWindowStart?: string;
      movementWindowEnd?: string;
    } = {},
  ): ProjectBrief {
    const summary = this.getProjectSummary(projectId);
    const workerSummary = this.getProjectWorkerSummary(projectId);
    const tasks = this.getProjectTasks(projectId);
    const taskById = new Map(tasks.map((task) => [task.id, task] as const));
    const taskItems = tasks.map((task) => this.toProjectTaskListItem(task, this.resolveTaskStatus(task)));
    const taskItemById = new Map(taskItems.map((task) => [task.id, task] as const));

    const recent_movement = tasks
      .flatMap((task) =>
        this.getDerivationHistory(task.id)
          .filter((run) =>
            (!options.movementWindowStart || run.timestamp >= options.movementWindowStart) &&
            (!options.movementWindowEnd || run.timestamp <= options.movementWindowEnd),
          )
          .map<ProjectBriefMovementItem>((run) => ({
            task_id: task.id,
            task_title: task.title,
            assignee_human_id: task.assignee_human_id,
            assignee_agent_id: task.assignee_agent_id,
            changed_at: run.timestamp,
            from_status: run.prior_state,
            to_status: run.output_state,
            rules_applied: run.rules_applied,
          })),
      )
      .sort((a, b) => b.changed_at.localeCompare(a.changed_at))
      .slice(0, BRIEF_MOVEMENT_LIMIT);

    const by_worker = this.buildProjectBriefWorkerGroups(tasks, taskItemById);
    const lead_attention_items: ProjectBriefAttentionItem[] = [
      ...summary.buckets.blocked.map((task) => ({
        kind: "blocked" as const,
        task,
        reason: "Task is blocked and may need lead intervention.",
      })),
      ...summary.buckets.needs_input.map((task) => ({
        kind: "needs_input" as const,
        task,
        reason: "Task needs input before work can continue.",
      })),
      ...summary.buckets.ready_for_review.map((task) => ({
        kind: "ready_for_review" as const,
        task,
        reason: "Task is ready for review.",
      })),
    ];

    const generated_at =
      options.movementWindowEnd ??
      recent_movement[0]?.changed_at ??
      summary.last_activity_at ??
      summary.project.updated_at;

    return {
      project: summary.project,
      generated_at,
      snapshot: {
        total_tasks: summary.total_tasks,
        counts_by_status: summary.counts_by_status,
        last_activity_at: summary.last_activity_at,
      },
      recent_movement,
      blocked: summary.buckets.blocked,
      needs_input: summary.buckets.needs_input,
      ready_for_review: summary.buckets.ready_for_review,
      by_worker,
      by_human: workerSummary.by_human,
      by_agent: workerSummary.by_agent,
      lead_attention_items,
      rendered_text: this.renderProjectBriefText(
        summary.project,
        summary,
        by_worker,
        workerSummary,
        recent_movement,
        lead_attention_items,
        taskById,
      ),
    };
  }

  private computeNextRunAt(timezone: string, deliveryHourLocal: number, after: Date): string {
    const start = new Date(after.getTime() + 60_000);
    for (let minutes = 0; minutes < 60 * 24 * 3; minutes += 1) {
      const candidate = new Date(start.getTime() + minutes * 60_000);
      const parts = this.getZonedDateParts(candidate, timezone);
      if (parts.hour === deliveryHourLocal && parts.minute === 0) {
        return candidate.toISOString();
      }
    }

    throw new Error(`Unable to compute next run time for timezone ${timezone}`);
  }

  private getZonedDateParts(date: Date, timezone: string): {
    year: number;
    month: number;
    day: number;
    hour: number;
    minute: number;
  } {
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
    const parts = Object.fromEntries(
      formatter.formatToParts(date)
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, Number.parseInt(part.value, 10)]),
    );
    return {
      year: parts.year,
      month: parts.month,
      day: parts.day,
      hour: parts.hour,
      minute: parts.minute,
    };
  }

  private buildProjectBriefWorkerGroups(
    tasks: Task[],
    taskItemById: Map<string, ProjectTaskListItem>,
  ): ProjectBriefWorkerGroup[] {
    const byWorker = new Map<
      string,
      {
        worker_id: string;
        tasks: Map<string, ProjectTaskListItem>;
        recent_activity_at: string;
        artifact_count: number;
      }
    >();

    for (const task of tasks) {
      for (const artifact of this.getArtifacts(task.id)) {
        const worker_id = artifact.worker_id;
        const taskItem = taskItemById.get(task.id);
        if (!worker_id || !taskItem) continue;

        const group = byWorker.get(worker_id) ?? {
          worker_id,
          tasks: new Map<string, ProjectTaskListItem>(),
          recent_activity_at: artifact.timestamp,
          artifact_count: 0,
        };

        group.tasks.set(task.id, taskItem);
        group.artifact_count += 1;
        if (artifact.timestamp > group.recent_activity_at) {
          group.recent_activity_at = artifact.timestamp;
        }

        byWorker.set(worker_id, group);
      }
    }

    return [...byWorker.values()]
      .map((group) => ({
        worker_id: group.worker_id,
        tasks: this.sortProjectTaskItems([...group.tasks.values()]),
        recent_activity_at: group.recent_activity_at,
        artifact_count: group.artifact_count,
      }))
      .sort((a, b) => {
        if (a.recent_activity_at === b.recent_activity_at) {
          return a.worker_id.localeCompare(b.worker_id);
        }
        return b.recent_activity_at.localeCompare(a.recent_activity_at);
      });
  }

  private renderProjectBriefText(
    project: Project,
    summary: ProjectSummary,
    byWorker: ProjectBriefWorkerGroup[],
    workerSummary: ProjectWorkerSummary,
    recentMovement: ProjectBriefMovementItem[],
    attentionItems: ProjectBriefAttentionItem[],
    taskById: Map<string, Task>,
  ): string {
    const lines: string[] = [];
    lines.push(`Project Brief: ${project.title} (${project.id})`);
    lines.push(
      `Snapshot: ${summary.total_tasks} task(s) | blocked ${summary.counts_by_status.blocked} | needs_input ${summary.counts_by_status.needs_input} | ready_for_review ${summary.counts_by_status.ready_for_review} | done ${summary.counts_by_status.done}`,
    );

    if (recentMovement.length > 0) {
      lines.push("Recent movement:");
      for (const item of recentMovement) {
        const agentSuffix = item.assignee_agent_id ? ` / ${item.assignee_agent_id}` : "";
        lines.push(
          `- ${item.changed_at}: ${item.task_id} ${item.from_status} -> ${item.to_status} (${item.assignee_human_id}${agentSuffix})`,
        );
      }
    } else {
      lines.push("Recent movement: none");
    }

    lines.push(`Blocked: ${summary.buckets.blocked.length}`);
    for (const task of summary.buckets.blocked) {
      lines.push(`- ${task.id} (${task.assignee_human_id})`);
    }

    lines.push(`Needs input: ${summary.buckets.needs_input.length}`);
    for (const task of summary.buckets.needs_input) {
      lines.push(`- ${task.id} (${task.assignee_human_id})`);
    }

    lines.push(`Ready for review: ${summary.buckets.ready_for_review.length}`);
    for (const task of summary.buckets.ready_for_review) {
      lines.push(`- ${task.id} (${task.assignee_human_id})`);
    }

    lines.push("By worker:");
    if (byWorker.length === 0) {
      lines.push("- none");
    } else {
      for (const group of byWorker) {
        const taskSummary = group.tasks.map((task) => `${task.id} (${task.status})`).join(", ");
        lines.push(
          `- ${group.worker_id}: ${taskSummary} | ${group.artifact_count} artifact(s) | latest ${group.recent_activity_at}`,
        );
      }
    }

    lines.push("By human:");
    for (const group of workerSummary.by_human) {
      lines.push(`- ${group.assignee_human_id}: ${group.tasks.length} task(s)`);
    }

    lines.push("By agent:");
    if (workerSummary.by_agent.length === 0) {
      lines.push("- none");
    } else {
      for (const group of workerSummary.by_agent) {
        lines.push(`- ${group.assignee_agent_id}: ${group.tasks.length} task(s)`);
      }
    }

    lines.push("Lead attention:");
    if (attentionItems.length === 0) {
      lines.push("- none");
    } else {
      for (const item of attentionItems) {
        const task = taskById.get(item.task.id);
        const agentSuffix = task?.assignee_agent_id ? ` / ${task.assignee_agent_id}` : "";
        lines.push(`- ${item.kind}: ${item.task.id} (${item.task.assignee_human_id}${agentSuffix})`);
      }
    }

    return lines.join("\n");
  }

  private resolveTaskStatus(task: Task): CanonicalStatus {
    return this.getTaskState(task.id)?.status ?? task.status;
  }

  private toProjectTaskListItem(task: Task, status: CanonicalStatus): ProjectTaskListItem {
    return {
      id: task.id,
      title: task.title,
      status,
      assignee_human_id: task.assignee_human_id,
      assignee_agent_id: task.assignee_agent_id,
      last_activity_at: task.last_activity_at,
    };
  }

  private sortProjectTaskItems(items: ProjectTaskListItem[]): ProjectTaskListItem[] {
    return items.sort((a, b) => {
      if (a.last_activity_at === b.last_activity_at) {
        return a.id.localeCompare(b.id);
      }
      return b.last_activity_at.localeCompare(a.last_activity_at);
    });
  }

  private readJson<T>(path: string): T | undefined {
    if (!existsSync(path)) return undefined;
    return JSON.parse(readFileSync(path, "utf-8")) as T;
  }
}

export function createEngine(options: EngineOptions): ArtifactLoopEngine {
  return new ArtifactLoopEngine(options);
}
