// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { resolve } from "node:path";
import { createEngine } from "../../engine.js";
import type {
  DerivationRun,
  InboxItem,
  IngestRequest,
  IngestResult,
  NormalizedArtifact,
  Organization,
  OrganizationBootstrapRequest,
  OrganizationBootstrapResult,
  Project,
  ProjectBrief,
  ProjectBriefRun,
  ProjectBriefSchedule,
  ProjectBriefScheduleUpsert,
  ProjectSummary,
  ProjectTaskLinkCreate,
  ProjectWorkerSummary,
  Task,
  TaskDraftSet,
  TaskDraftSetApproveRequest,
  TaskDraftSetGenerateRequest,
  TaskDraftSetRejectRequest,
  TaskMessage,
  TaskMessageCreate,
  TaskState,
  Team,
  TeamCreate,
  TeamMembership,
  TeamMembershipCreate,
  UsageStats,
  CanonicalStatus,
  Worker,
  WorkerAgent,
  WorkerAgentCreate,
  WorkerCreate,
  Assignment,
  AssignmentCreate,
  ProjectCreate,
  ScheduledBriefRunResult,
} from "../../types.js";

const DEFAULT_REMOTE_TIMEOUT_MS = 10_000;

export interface ArtifactLoopClient {
  bootstrapOrganization(input: OrganizationBootstrapRequest): Promise<OrganizationBootstrapResult>;
  getOrganization(): Promise<Organization | undefined>;
  createTeam(input: TeamCreate): Promise<Team>;
  getTeams(): Promise<Team[]>;
  getTeam(teamId: string): Promise<Team | undefined>;
  addTeamMember(teamId: string, input: TeamMembershipCreate): Promise<TeamMembership>;
  getTeamMembers(teamId: string): Promise<TeamMembership[]>;
  getTask(taskId: string): Promise<Task | undefined>;
  getTaskState(taskId: string): Promise<TaskState | undefined>;
  getTaskArtifacts(taskId: string): Promise<NormalizedArtifact[]>;
  getTaskHistory(taskId: string): Promise<DerivationRun[]>;
  createTaskAssignment(taskId: string, input: AssignmentCreate): Promise<Assignment>;
  getTaskMessages(taskId: string): Promise<TaskMessage[]>;
  createTaskMessage(taskId: string, input: TaskMessageCreate): Promise<TaskMessage>;
  acknowledgeMessage(messageId: string): Promise<TaskMessage>;
  createProject(input: ProjectCreate): Promise<Project>;
  getProjects(): Promise<Project[]>;
  getProject(projectId: string): Promise<Project | undefined>;
  getProjectTasks(
    projectId: string,
    filters?: { status?: CanonicalStatus; assignee_human_id?: string; assignee_agent_id?: string },
  ): Promise<Task[]>;
  getProjectSummary(projectId: string): Promise<ProjectSummary>;
  getProjectWorkerSummary(projectId: string): Promise<ProjectWorkerSummary>;
  getProjectBrief(projectId: string): Promise<ProjectBrief>;
  createTaskDraftSet(projectId: string, input: TaskDraftSetGenerateRequest): Promise<TaskDraftSet>;
  getTaskDraftSets(projectId: string): Promise<TaskDraftSet[]>;
  getTaskDraftSet(projectId: string, draftSetId: string): Promise<TaskDraftSet | undefined>;
  approveTaskDraftSet(
    projectId: string,
    draftSetId: string,
    input: TaskDraftSetApproveRequest,
  ): Promise<{ draftSet: TaskDraftSet; tasks: Task[] }>;
  rejectTaskDraftSet(
    projectId: string,
    draftSetId: string,
    input: TaskDraftSetRejectRequest,
  ): Promise<TaskDraftSet>;
  createWorker(input: WorkerCreate): Promise<Worker>;
  getWorkers(): Promise<Worker[]>;
  getWorker(workerId: string): Promise<Worker | undefined>;
  createWorkerAgent(workerId: string, input: WorkerAgentCreate): Promise<WorkerAgent>;
  getWorkerAgents(workerId: string): Promise<WorkerAgent[]>;
  getWorkerAgentInbox(agentId: string, status?: string): Promise<InboxItem[]>;
  acknowledgeInboxItem(inboxItemId: string): Promise<InboxItem>;
  upsertProjectBriefSchedule(projectId: string, input: ProjectBriefScheduleUpsert): Promise<ProjectBriefSchedule>;
  getProjectBriefSchedule(projectId: string): Promise<ProjectBriefSchedule | undefined>;
  getProjectBriefRuns(projectId: string): Promise<ProjectBriefRun[]>;
  getLatestProjectBriefRun(projectId: string): Promise<ProjectBriefRun | undefined>;
  ingest(request: IngestRequest): Promise<IngestResult>;
  getStats(): Promise<UsageStats>;
}

export interface RemoteCapableCliOpts {
  dataDir?: string;
  serviceUrl?: string;
}

export class RemoteClientError extends Error {
  constructor(
    readonly serviceUrl: string,
    readonly path: string,
    message: string,
    readonly statusCode?: number,
  ) {
    super(message);
  }
}

function normalizeServiceUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

function formatRemoteError(serviceUrl: string, message: string): string {
  return `Remote service ${serviceUrl}: ${message}`;
}

async function parseJsonResponse<T>(response: Response, serviceUrl: string, path: string): Promise<T> {
  let text: string;
  try {
    text = await response.text();
  } catch (err) {
    throw new RemoteClientError(
      serviceUrl,
      path,
      formatRemoteError(serviceUrl, `failed to read response body (${(err as Error).message})`),
      response.status,
    );
  }

  if (text.length === 0) {
    throw new RemoteClientError(
      serviceUrl,
      path,
      formatRemoteError(serviceUrl, `empty response from ${path}`),
      response.status,
    );
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throw new RemoteClientError(
      serviceUrl,
      path,
      formatRemoteError(serviceUrl, `invalid JSON response from ${path}`),
      response.status,
    );
  }
}

class RemoteArtifactLoopClient implements ArtifactLoopClient {
  constructor(private readonly serviceUrl: string) {}

  private async request<T>(
    path: string,
    init?: RequestInit,
    notFoundValue?: T,
  ): Promise<T> {
    const url = `${this.serviceUrl}${path}`;
    let response: Response;
    try {
      response = await fetch(url, {
        ...init,
        signal: AbortSignal.timeout(DEFAULT_REMOTE_TIMEOUT_MS),
      });
    } catch (err) {
      throw new RemoteClientError(
        this.serviceUrl,
        path,
        formatRemoteError(this.serviceUrl, `request failed for ${path} (${(err as Error).message})`),
      );
    }

    if (response.status === 404 && notFoundValue !== undefined) {
      return notFoundValue;
    }

    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try {
        const parsed = await parseJsonResponse<{ error?: string }>(response, this.serviceUrl, path);
        message = parsed.error ?? message;
      } catch (parseErr) {
        if (parseErr instanceof RemoteClientError) {
          throw parseErr;
        }
      }
      throw new RemoteClientError(
        this.serviceUrl,
        path,
        formatRemoteError(this.serviceUrl, message),
        response.status,
      );
    }

    return parseJsonResponse<T>(response, this.serviceUrl, path);
  }

  bootstrapOrganization(input: OrganizationBootstrapRequest): Promise<OrganizationBootstrapResult> {
    return this.request<OrganizationBootstrapResult>("/org/bootstrap", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  getOrganization(): Promise<Organization | undefined> {
    return this.request<Organization | undefined>("/org", undefined, undefined);
  }

  createTeam(input: TeamCreate): Promise<Team> {
    return this.request<Team>("/teams", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  getTeams(): Promise<Team[]> {
    return this.request<Team[]>("/teams", undefined, []);
  }

  getTeam(teamId: string): Promise<Team | undefined> {
    return this.request<Team | undefined>(`/teams/${encodeURIComponent(teamId)}`, undefined, undefined);
  }

  addTeamMember(teamId: string, input: TeamMembershipCreate): Promise<TeamMembership> {
    return this.request<TeamMembership>(`/teams/${encodeURIComponent(teamId)}/members`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  getTeamMembers(teamId: string): Promise<TeamMembership[]> {
    return this.request<TeamMembership[]>(`/teams/${encodeURIComponent(teamId)}/members`, undefined, []);
  }

  getTask(taskId: string): Promise<Task | undefined> {
    return this.request<Task | undefined>(`/tasks/${encodeURIComponent(taskId)}`, undefined, undefined);
  }

  getTaskState(taskId: string): Promise<TaskState | undefined> {
    return this.request<TaskState | undefined>(
      `/tasks/${encodeURIComponent(taskId)}/state`,
      undefined,
      undefined,
    );
  }

  getTaskArtifacts(taskId: string): Promise<NormalizedArtifact[]> {
    return this.request<NormalizedArtifact[]>(
      `/tasks/${encodeURIComponent(taskId)}/artifacts`,
      undefined,
      [],
    );
  }

  getTaskHistory(taskId: string): Promise<DerivationRun[]> {
    return this.request<DerivationRun[]>(
      `/tasks/${encodeURIComponent(taskId)}/history`,
      undefined,
      [],
    );
  }

  createTaskAssignment(taskId: string, input: AssignmentCreate): Promise<Assignment> {
    return this.request<Assignment>(`/tasks/${encodeURIComponent(taskId)}/assignments`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  getTaskMessages(taskId: string): Promise<TaskMessage[]> {
    return this.request<TaskMessage[]>(`/tasks/${encodeURIComponent(taskId)}/messages`, undefined, []);
  }

  createTaskMessage(taskId: string, input: TaskMessageCreate): Promise<TaskMessage> {
    return this.request<TaskMessage>(`/tasks/${encodeURIComponent(taskId)}/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  acknowledgeMessage(messageId: string): Promise<TaskMessage> {
    return this.request<TaskMessage>(`/messages/${encodeURIComponent(messageId)}/ack`, {
      method: "POST",
    });
  }

  createProject(input: ProjectCreate): Promise<Project> {
    return this.request<Project>("/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  getProjects(): Promise<Project[]> {
    return this.request<Project[]>("/projects", undefined, []);
  }

  getProject(projectId: string): Promise<Project | undefined> {
    return this.request<Project | undefined>(`/projects/${encodeURIComponent(projectId)}`, undefined, undefined);
  }

  getProjectTasks(
    projectId: string,
    filters: { status?: CanonicalStatus; assignee_human_id?: string; assignee_agent_id?: string } = {},
  ): Promise<Task[]> {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.assignee_human_id) params.set("assignee_human_id", filters.assignee_human_id);
    if (filters.assignee_agent_id) params.set("assignee_agent_id", filters.assignee_agent_id);
    const suffix = params.size > 0 ? `?${params.toString()}` : "";
    return this.request<Task[]>(`/projects/${encodeURIComponent(projectId)}/tasks${suffix}`, undefined, []);
  }

  getProjectSummary(projectId: string): Promise<ProjectSummary> {
    return this.request<ProjectSummary>(`/projects/${encodeURIComponent(projectId)}/summary`);
  }

  getProjectWorkerSummary(projectId: string): Promise<ProjectWorkerSummary> {
    return this.request<ProjectWorkerSummary>(`/projects/${encodeURIComponent(projectId)}/workers`);
  }

  getProjectBrief(projectId: string): Promise<ProjectBrief> {
    return this.request<ProjectBrief>(`/projects/${encodeURIComponent(projectId)}/brief`);
  }

  createTaskDraftSet(projectId: string, input: TaskDraftSetGenerateRequest): Promise<TaskDraftSet> {
    return this.request<TaskDraftSet>(`/projects/${encodeURIComponent(projectId)}/task-draft-sets/generate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  getTaskDraftSets(projectId: string): Promise<TaskDraftSet[]> {
    return this.request<TaskDraftSet[]>(`/projects/${encodeURIComponent(projectId)}/task-draft-sets`, undefined, []);
  }

  getTaskDraftSet(projectId: string, draftSetId: string): Promise<TaskDraftSet | undefined> {
    return this.request<TaskDraftSet | undefined>(
      `/projects/${encodeURIComponent(projectId)}/task-draft-sets/${encodeURIComponent(draftSetId)}`,
      undefined,
      undefined,
    );
  }

  approveTaskDraftSet(projectId: string, draftSetId: string, input: TaskDraftSetApproveRequest): Promise<{ draftSet: TaskDraftSet; tasks: Task[] }> {
    return this.request<{ draftSet: TaskDraftSet; tasks: Task[] }>(
      `/projects/${encodeURIComponent(projectId)}/task-draft-sets/${encodeURIComponent(draftSetId)}/approve`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(input),
      },
    );
  }

  rejectTaskDraftSet(projectId: string, draftSetId: string, input: TaskDraftSetRejectRequest): Promise<TaskDraftSet> {
    return this.request<TaskDraftSet>(
      `/projects/${encodeURIComponent(projectId)}/task-draft-sets/${encodeURIComponent(draftSetId)}/reject`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(input),
      },
    );
  }

  createWorker(input: WorkerCreate): Promise<Worker> {
    return this.request<Worker>("/workers", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  getWorkers(): Promise<Worker[]> {
    return this.request<Worker[]>("/workers", undefined, []);
  }

  getWorker(workerId: string): Promise<Worker | undefined> {
    return this.request<Worker | undefined>(`/workers/${encodeURIComponent(workerId)}`, undefined, undefined);
  }

  createWorkerAgent(workerId: string, input: WorkerAgentCreate): Promise<WorkerAgent> {
    return this.request<WorkerAgent>(`/workers/${encodeURIComponent(workerId)}/agents`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  getWorkerAgents(workerId: string): Promise<WorkerAgent[]> {
    return this.request<WorkerAgent[]>(`/workers/${encodeURIComponent(workerId)}/agents`, undefined, []);
  }

  getWorkerAgentInbox(agentId: string, status?: string): Promise<InboxItem[]> {
    const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
    return this.request<InboxItem[]>(`/worker-agents/${encodeURIComponent(agentId)}/inbox${suffix}`, undefined, []);
  }

  acknowledgeInboxItem(inboxItemId: string): Promise<InboxItem> {
    return this.request<InboxItem>(`/inbox/${encodeURIComponent(inboxItemId)}/ack`, { method: "POST" });
  }

  upsertProjectBriefSchedule(projectId: string, input: ProjectBriefScheduleUpsert): Promise<ProjectBriefSchedule> {
    return this.request<ProjectBriefSchedule>(`/projects/${encodeURIComponent(projectId)}/brief-schedule`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  getProjectBriefSchedule(projectId: string): Promise<ProjectBriefSchedule | undefined> {
    return this.request<ProjectBriefSchedule | undefined>(
      `/projects/${encodeURIComponent(projectId)}/brief-schedule`,
      undefined,
      undefined,
    );
  }

  getProjectBriefRuns(projectId: string): Promise<ProjectBriefRun[]> {
    return this.request<ProjectBriefRun[]>(`/projects/${encodeURIComponent(projectId)}/brief-runs`, undefined, []);
  }

  getLatestProjectBriefRun(projectId: string): Promise<ProjectBriefRun | undefined> {
    return this.request<ProjectBriefRun | undefined>(
      `/projects/${encodeURIComponent(projectId)}/brief-runs/latest`,
      undefined,
      undefined,
    );
  }

  ingest(request: IngestRequest): Promise<IngestResult> {
    return this.request<IngestResult>("/artifacts/ingest", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    });
  }

  getStats(): Promise<UsageStats> {
    return this.request<UsageStats>("/stats");
  }
}

class LocalArtifactLoopClient implements ArtifactLoopClient {
  private readonly engine;

  constructor(dataDir: string) {
    this.engine = createEngine({ dataDir });
  }

  bootstrapOrganization(input: OrganizationBootstrapRequest): Promise<OrganizationBootstrapResult> {
    return Promise.resolve(this.engine.bootstrapOrganization(input));
  }

  getOrganization(): Promise<Organization | undefined> {
    return Promise.resolve(this.engine.getOrganization());
  }

  createTeam(input: TeamCreate): Promise<Team> {
    return Promise.resolve(this.engine.createTeam(input));
  }

  getTeams(): Promise<Team[]> {
    return Promise.resolve(this.engine.getTeams());
  }

  getTeam(teamId: string): Promise<Team | undefined> {
    return Promise.resolve(this.engine.getTeam(teamId));
  }

  addTeamMember(teamId: string, input: TeamMembershipCreate): Promise<TeamMembership> {
    return Promise.resolve(this.engine.addTeamMember(teamId, input));
  }

  getTeamMembers(teamId: string): Promise<TeamMembership[]> {
    return Promise.resolve(this.engine.getTeamMembers(teamId));
  }

  getTask(taskId: string): Promise<Task | undefined> {
    return Promise.resolve(this.engine.getTask(taskId));
  }

  getTaskState(taskId: string): Promise<TaskState | undefined> {
    return Promise.resolve(this.engine.getTaskState(taskId));
  }

  getTaskArtifacts(taskId: string): Promise<NormalizedArtifact[]> {
    return Promise.resolve(this.engine.getArtifacts(taskId));
  }

  getTaskHistory(taskId: string): Promise<DerivationRun[]> {
    return Promise.resolve(this.engine.getDerivationHistory(taskId));
  }

  createTaskAssignment(taskId: string, input: AssignmentCreate): Promise<Assignment> {
    return Promise.resolve(this.engine.createAssignment(taskId, input));
  }

  getTaskMessages(taskId: string): Promise<TaskMessage[]> {
    return Promise.resolve(this.engine.getTaskMessages(taskId));
  }

  createTaskMessage(taskId: string, input: TaskMessageCreate): Promise<TaskMessage> {
    return Promise.resolve(this.engine.createTaskMessage(taskId, input));
  }

  acknowledgeMessage(messageId: string): Promise<TaskMessage> {
    return Promise.resolve(this.engine.acknowledgeTaskMessage(messageId));
  }

  createProject(input: ProjectCreate): Promise<Project> {
    return Promise.resolve(this.engine.createProject(input));
  }

  getProjects(): Promise<Project[]> {
    return Promise.resolve(this.engine.getProjects());
  }

  getProject(projectId: string): Promise<Project | undefined> {
    return Promise.resolve(this.engine.getProject(projectId));
  }

  getProjectTasks(
    projectId: string,
    filters: { status?: CanonicalStatus; assignee_human_id?: string; assignee_agent_id?: string } = {},
  ): Promise<Task[]> {
    return Promise.resolve(this.engine.getProjectTasks(projectId, filters));
  }

  getProjectSummary(projectId: string): Promise<ProjectSummary> {
    return Promise.resolve(this.engine.getProjectSummary(projectId));
  }

  getProjectWorkerSummary(projectId: string): Promise<ProjectWorkerSummary> {
    return Promise.resolve(this.engine.getProjectWorkerSummary(projectId));
  }

  getProjectBrief(projectId: string): Promise<ProjectBrief> {
    return Promise.resolve(this.engine.getProjectBrief(projectId));
  }

  createTaskDraftSet(projectId: string, input: TaskDraftSetGenerateRequest): Promise<TaskDraftSet> {
    return Promise.resolve(this.engine.createTaskDraftSet(projectId, input));
  }

  getTaskDraftSets(projectId: string): Promise<TaskDraftSet[]> {
    return Promise.resolve(this.engine.getTaskDraftSets(projectId));
  }

  getTaskDraftSet(projectId: string, draftSetId: string): Promise<TaskDraftSet | undefined> {
    return Promise.resolve(this.engine.getTaskDraftSet(projectId, draftSetId));
  }

  approveTaskDraftSet(projectId: string, draftSetId: string, input: TaskDraftSetApproveRequest): Promise<{ draftSet: TaskDraftSet; tasks: Task[] }> {
    return Promise.resolve(this.engine.approveTaskDraftSet(projectId, draftSetId, input));
  }

  rejectTaskDraftSet(projectId: string, draftSetId: string, input: TaskDraftSetRejectRequest): Promise<TaskDraftSet> {
    return Promise.resolve(this.engine.rejectTaskDraftSet(projectId, draftSetId, input));
  }

  createWorker(input: WorkerCreate): Promise<Worker> {
    return Promise.resolve(this.engine.createWorker(input));
  }

  getWorkers(): Promise<Worker[]> {
    return Promise.resolve(this.engine.getWorkers());
  }

  getWorker(workerId: string): Promise<Worker | undefined> {
    return Promise.resolve(this.engine.getWorker(workerId));
  }

  createWorkerAgent(workerId: string, input: WorkerAgentCreate): Promise<WorkerAgent> {
    return Promise.resolve(this.engine.createWorkerAgent(workerId, input));
  }

  getWorkerAgents(workerId: string): Promise<WorkerAgent[]> {
    return Promise.resolve(this.engine.getWorkerAgents(workerId));
  }

  getWorkerAgentInbox(agentId: string, status?: string): Promise<InboxItem[]> {
    return Promise.resolve(this.engine.getWorkerAgentInbox(agentId, { status: status as never }));
  }

  acknowledgeInboxItem(inboxItemId: string): Promise<InboxItem> {
    return Promise.resolve(this.engine.acknowledgeInboxItem(inboxItemId));
  }

  upsertProjectBriefSchedule(projectId: string, input: ProjectBriefScheduleUpsert): Promise<ProjectBriefSchedule> {
    return Promise.resolve(this.engine.upsertProjectBriefSchedule(projectId, input));
  }

  getProjectBriefSchedule(projectId: string): Promise<ProjectBriefSchedule | undefined> {
    return Promise.resolve(this.engine.getProjectBriefSchedule(projectId));
  }

  getProjectBriefRuns(projectId: string): Promise<ProjectBriefRun[]> {
    return Promise.resolve(this.engine.getProjectBriefRuns(projectId));
  }

  getLatestProjectBriefRun(projectId: string): Promise<ProjectBriefRun | undefined> {
    return Promise.resolve(this.engine.getLatestProjectBriefRun(projectId));
  }

  ingest(request: IngestRequest): Promise<IngestResult> {
    return Promise.resolve(this.engine.ingest(request.artifact, request.context));
  }

  getStats(): Promise<UsageStats> {
    return Promise.resolve(this.engine.getUsageStats());
  }
}

export function resolveServiceUrl(opts: { serviceUrl?: string }): string | undefined {
  const url = opts.serviceUrl ?? process.env.ARTIFACT_LOOP_SERVICE_URL;
  return url ? normalizeServiceUrl(url) : undefined;
}

export function resolveArtifactLoopClient(opts: RemoteCapableCliOpts): ArtifactLoopClient {
  const serviceUrl = resolveServiceUrl(opts);
  if (serviceUrl) {
    return new RemoteArtifactLoopClient(serviceUrl);
  }

  const dataDir = resolve(opts.dataDir ?? ".artifact-loop");
  return new LocalArtifactLoopClient(dataDir);
}

export function resolveArtifactSource(opts: { serviceUrl?: string }): string {
  return resolveServiceUrl(opts) ? "remote_worker_connector" : "cli";
}
