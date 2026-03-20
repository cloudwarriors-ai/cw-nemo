// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { resolve } from "node:path";
import { createEngine, type ArtifactLoopEngine } from "../engine.js";
import type {
  AssignmentCreate,
  CanonicalStatus,
  IngestRequest,
  OrganizationBootstrapRequest,
  ProjectBriefScheduleUpsert,
  ProjectCreate,
  ProjectTaskLinkCreate,
  TeamCreate,
  TeamMembershipCreate,
  TaskDraftSetApproveRequest,
  TaskDraftSetGenerateRequest,
  TaskDraftSetRejectRequest,
  TaskMessageCreate,
  Task,
  TaskCreate,
  WorkerAgentCreate,
  WorkerCreate,
} from "../types.js";
import { CONTRACT_IDS, getContractValidator } from "./schema-validator.js";

export interface ArtifactLoopServerOptions {
  dataDir: string;
}

export interface ListenOptions extends ArtifactLoopServerOptions {
  host: string;
  port: number;
}

function sendJson(res: ServerResponse, statusCode: number, body: unknown): void {
  res.writeHead(statusCode, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body, null, 2));
}

function sendError(res: ServerResponse, statusCode: number, message: string): void {
  sendJson(res, statusCode, { error: message });
}

function isCanonicalStatus(value: string): value is CanonicalStatus {
  return [
    "not_started",
    "in_progress",
    "needs_input",
    "blocked",
    "ready_for_review",
    "done",
  ].includes(value);
}

async function readJsonBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }

  const raw = Buffer.concat(chunks).toString("utf-8");
  if (raw.length === 0) {
    throw new Error("Request body is required");
  }

  try {
    return JSON.parse(raw) as unknown;
  } catch {
    throw new Error("Request body must be valid JSON");
  }
}

function splitPath(url: URL): string[] {
  return url.pathname.split("/").filter(Boolean);
}

function filterTasks(tasks: Task[], url: URL): Task[] {
  const status = url.searchParams.get("status");
  const assigneeHumanId = url.searchParams.get("assignee_human_id");
  const assigneeAgentId = url.searchParams.get("assignee_agent_id");
  const projectId = url.searchParams.get("project_id");

  let filtered = tasks;
  if (status) {
    if (!isCanonicalStatus(status)) {
      return [];
    }
    filtered = filtered.filter((task) => task.status === status);
  }
  if (assigneeHumanId) {
    filtered = filtered.filter((task) => task.assignee_human_id === assigneeHumanId);
  }
  if (assigneeAgentId) {
    filtered = filtered.filter((task) => task.assignee_agent_id === assigneeAgentId);
  }
  if (projectId) {
    filtered = filtered.filter((task) => task.project_id === projectId);
  }
  return filtered;
}

function requireTask(engine: ArtifactLoopEngine, taskId: string): Task | undefined {
  return engine.getTask(taskId);
}

function mapMutationError(err: unknown): { statusCode: number; message: string } {
  const message = err instanceof Error ? err.message : "Request failed";
  if (message.startsWith("Task already exists:")) {
    return { statusCode: 409, message };
  }
  if (message.startsWith("Project already exists:")) {
    return { statusCode: 409, message };
  }
  if (message === "Organization already exists") {
    return { statusCode: 409, message };
  }
  if (message.startsWith("Team already exists:")) {
    return { statusCode: 409, message };
  }
  if (message.startsWith("Member already belongs to different team:")) {
    return { statusCode: 409, message };
  }
  if (message === "Organization not bootstrapped") {
    return { statusCode: 400, message };
  }
  if (message.startsWith("Worker already exists:")) {
    return { statusCode: 409, message };
  }
  if (message.startsWith("Worker agent already exists:")) {
    return { statusCode: 409, message };
  }
  if (message.startsWith("Task already linked to different project:")) {
    return { statusCode: 409, message };
  }
  if (message.startsWith("Task draft set is not approvable:")) {
    return { statusCode: 409, message };
  }
  if (message.startsWith("Task draft set is not rejectable:")) {
    return { statusCode: 409, message };
  }
  if (message.startsWith("Duplicate task draft id:")) {
    return { statusCode: 409, message };
  }
  if (message.startsWith("Task not found:")) {
    return { statusCode: 404, message };
  }
  if (message.startsWith("Project not found:")) {
    return { statusCode: 404, message };
  }
  if (message.startsWith("Team not found:")) {
    return { statusCode: 404, message };
  }
  if (message.startsWith("Worker not found:")) {
    return { statusCode: 404, message };
  }
  if (message.startsWith("Worker agent not found:")) {
    return { statusCode: 404, message };
  }
  if (message.startsWith("Task draft set not found:")) {
    return { statusCode: 404, message };
  }
  if (message.startsWith("Inbox item not found:")) {
    return { statusCode: 404, message };
  }
  if (message.startsWith("Message not found:")) {
    return { statusCode: 404, message };
  }
  if (message.startsWith("Member lacks required team role:")) {
    return { statusCode: 403, message };
  }
  if (message.startsWith("Member lacks required org role:")) {
    return { statusCode: 403, message };
  }
  if (message.startsWith("Member is not active in team:")) {
    return { statusCode: 403, message };
  }
  if (message.startsWith("Team-scoped assignment requires assigned_by:")) {
    return { statusCode: 400, message };
  }
  return { statusCode: 400, message };
}

export function createArtifactLoopServer(options: ArtifactLoopServerOptions): Server {
  const dataDir = resolve(options.dataDir);
  const engine = createEngine({ dataDir });
  const validator = getContractValidator();

  return createServer(async (req, res) => {
    try {
      if (!req.url || !req.method) {
        sendError(res, 400, "Request is missing URL or method");
        return;
      }

      const url = new URL(req.url, "http://artifact-loop.local");
      const path = splitPath(url);

      if (req.method === "GET" && path.length === 1 && path[0] === "health") {
        sendJson(res, 200, { ok: true, service: "artifact-loop", data_dir: dataDir });
        return;
      }

      if (req.method === "POST" && path.length === 2 && path[0] === "org" && path[1] === "bootstrap") {
        const body = await readJsonBody(req);
        validator.assertValid(CONTRACT_IDS.organizationBootstrap, body);
        sendJson(res, 201, engine.bootstrapOrganization(body as OrganizationBootstrapRequest));
        return;
      }

      if (req.method === "GET" && path.length === 1 && path[0] === "org") {
        const organization = engine.getOrganization();
        if (!organization) {
          sendError(res, 404, "Organization not bootstrapped");
          return;
        }
        sendJson(res, 200, organization);
        return;
      }

      if (req.method === "POST" && path.length === 1 && path[0] === "tasks") {
        const body = await readJsonBody(req);
        validator.assertValid(CONTRACT_IDS.taskCreate, body);
        const task = engine.createTask(body as TaskCreate);
        sendJson(res, 201, task);
        return;
      }

      if (req.method === "POST" && path.length === 1 && path[0] === "workers") {
        const body = await readJsonBody(req);
        validator.assertValid(CONTRACT_IDS.workerCreate, body);
        sendJson(res, 201, engine.createWorker(body as WorkerCreate));
        return;
      }

      if (req.method === "POST" && path.length === 1 && path[0] === "projects") {
        const body = await readJsonBody(req);
        validator.assertValid(CONTRACT_IDS.projectCreate, body);
        const project = engine.createProject(body as ProjectCreate);
        sendJson(res, 201, project);
        return;
      }

      if (req.method === "POST" && path.length === 1 && path[0] === "teams") {
        const body = await readJsonBody(req);
        validator.assertValid(CONTRACT_IDS.teamCreate, body);
        sendJson(res, 201, engine.createTeam(body as TeamCreate));
        return;
      }

      if (req.method === "GET" && path.length === 1 && path[0] === "tasks") {
        sendJson(res, 200, filterTasks(engine.getTasks(), url));
        return;
      }

      if (req.method === "GET" && path.length === 1 && path[0] === "projects") {
        sendJson(res, 200, engine.getProjects());
        return;
      }

      if (req.method === "GET" && path.length === 1 && path[0] === "workers") {
        sendJson(res, 200, engine.getWorkers());
        return;
      }

      if (req.method === "GET" && path.length === 1 && path[0] === "teams") {
        sendJson(res, 200, engine.getTeams());
        return;
      }

      if (req.method === "POST" && path.length === 2 && path[0] === "artifacts" && path[1] === "ingest") {
        const body = await readJsonBody(req);
        validator.assertValid(CONTRACT_IDS.ingestRequest, body);
        const result = engine.ingest(
          (body as IngestRequest).artifact,
          (body as IngestRequest).context,
        );
        sendJson(res, 201, result);
        return;
      }

      if (req.method === "GET" && path.length === 1 && path[0] === "stats") {
        sendJson(res, 200, engine.getUsageStats());
        return;
      }

      if (path.length >= 2 && path[0] === "workers") {
        const workerId = decodeURIComponent(path[1]);
        const worker = engine.getWorker(workerId);
        if (!worker) {
          sendError(res, 404, `Worker not found: ${workerId}`);
          return;
        }

        if (req.method === "GET" && path.length === 2) {
          sendJson(res, 200, worker);
          return;
        }

        if (req.method === "POST" && path.length === 3 && path[2] === "agents") {
          const body = await readJsonBody(req);
          validator.assertValid(CONTRACT_IDS.workerAgentCreate, body);
          sendJson(res, 201, engine.createWorkerAgent(workerId, body as WorkerAgentCreate));
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "agents") {
          sendJson(res, 200, engine.getWorkerAgents(workerId));
          return;
        }
      }

      if (path.length >= 2 && path[0] === "teams") {
        const teamId = decodeURIComponent(path[1]);
        const team = engine.getTeam(teamId);
        if (!team) {
          sendError(res, 404, `Team not found: ${teamId}`);
          return;
        }

        if (req.method === "GET" && path.length === 2) {
          sendJson(res, 200, team);
          return;
        }

        if (req.method === "POST" && path.length === 3 && path[2] === "members") {
          const body = await readJsonBody(req);
          validator.assertValid(CONTRACT_IDS.teamMembershipCreate, body);
          sendJson(res, 201, engine.addTeamMember(teamId, body as TeamMembershipCreate));
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "members") {
          sendJson(res, 200, engine.getTeamMembers(teamId));
          return;
        }
      }

      if (path.length >= 2 && path[0] === "worker-agents") {
        const agentId = decodeURIComponent(path[1]);
        const agent = engine.getWorkerAgent(agentId);
        if (!agent) {
          sendError(res, 404, `Worker agent not found: ${agentId}`);
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "inbox") {
          const statusParam = url.searchParams.get("status") ?? undefined;
          sendJson(
            res,
            200,
            engine.getWorkerAgentInbox(agentId, {
              status: statusParam as never,
            }),
          );
          return;
        }
      }

      if (req.method === "POST" && path.length === 3 && path[0] === "inbox" && path[2] === "ack") {
        const inboxItemId = decodeURIComponent(path[1]);
        sendJson(res, 200, engine.acknowledgeInboxItem(inboxItemId));
        return;
      }

      if (req.method === "POST" && path.length === 3 && path[0] === "messages" && path[2] === "ack") {
        const messageId = decodeURIComponent(path[1]);
        sendJson(res, 200, engine.acknowledgeTaskMessage(messageId));
        return;
      }

      if (path.length >= 2 && path[0] === "projects") {
        const projectId = decodeURIComponent(path[1]);
        const project = engine.getProject(projectId);
        if (!project) {
          sendError(res, 404, `Project not found: ${projectId}`);
          return;
        }

        if (req.method === "GET" && path.length === 2) {
          sendJson(res, 200, project);
          return;
        }

        if (req.method === "POST" && path.length === 3 && path[2] === "tasks") {
          const body = await readJsonBody(req);
          validator.assertValid(CONTRACT_IDS.projectTaskLinkCreate, body);
          const task = engine.assignTaskToProject(projectId, (body as ProjectTaskLinkCreate).task_id);
          sendJson(res, 200, task);
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "tasks") {
          const statusParam = url.searchParams.get("status");
          const status = statusParam && isCanonicalStatus(statusParam) ? statusParam : undefined;
          const assigneeHumanId = url.searchParams.get("assignee_human_id") ?? undefined;
          const assigneeAgentId = url.searchParams.get("assignee_agent_id") ?? undefined;
          sendJson(
            res,
            200,
            engine.getProjectTasks(projectId, {
              status,
              assignee_human_id: assigneeHumanId,
              assignee_agent_id: assigneeAgentId,
            }),
          );
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "summary") {
          sendJson(res, 200, engine.getProjectSummary(projectId));
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "workers") {
          sendJson(res, 200, engine.getProjectWorkerSummary(projectId));
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "brief") {
          sendJson(res, 200, engine.getProjectBrief(projectId));
          return;
        }

        if (path.length >= 3 && path[2] === "task-draft-sets") {
          if (req.method === "POST" && path.length === 4 && path[3] === "generate") {
            const body = await readJsonBody(req);
            validator.assertValid(CONTRACT_IDS.taskDraftSetGenerate, body);
            sendJson(res, 201, engine.createTaskDraftSet(projectId, body as TaskDraftSetGenerateRequest));
            return;
          }

          if (req.method === "GET" && path.length === 3) {
            sendJson(res, 200, engine.getTaskDraftSets(projectId));
            return;
          }

          if (path.length === 4) {
            const draftSetId = decodeURIComponent(path[3]);
            const draftSet = engine.getTaskDraftSet(projectId, draftSetId);
            if (!draftSet) {
              sendError(res, 404, `Task draft set not found: ${draftSetId}`);
              return;
            }
            if (req.method === "GET") {
              sendJson(res, 200, draftSet);
              return;
            }
          }

          if (path.length === 5) {
            const draftSetId = decodeURIComponent(path[3]);
            if (req.method === "POST" && path[4] === "approve") {
              const body = await readJsonBody(req);
              validator.assertValid(CONTRACT_IDS.taskDraftSetApprove, body);
              sendJson(res, 200, engine.approveTaskDraftSet(projectId, draftSetId, body as TaskDraftSetApproveRequest));
              return;
            }

            if (req.method === "POST" && path[4] === "reject") {
              const body = await readJsonBody(req);
              validator.assertValid(CONTRACT_IDS.taskDraftSetReject, body);
              sendJson(res, 200, engine.rejectTaskDraftSet(projectId, draftSetId, body as TaskDraftSetRejectRequest));
              return;
            }
          }
        }

        if (path.length >= 3 && path[2] === "brief-schedule") {
          if (req.method === "PUT" && path.length === 3) {
            const body = await readJsonBody(req);
            validator.assertValid(CONTRACT_IDS.projectBriefScheduleUpsert, body);
            sendJson(res, 200, engine.upsertProjectBriefSchedule(projectId, body as ProjectBriefScheduleUpsert));
            return;
          }

          if (req.method === "GET" && path.length === 3) {
            const schedule = engine.getProjectBriefSchedule(projectId);
            if (!schedule) {
              sendError(res, 404, `Project brief schedule not found: ${projectId}`);
              return;
            }
            sendJson(res, 200, schedule);
            return;
          }
        }

        if (path.length >= 3 && path[2] === "brief-runs") {
          if (req.method === "GET" && path.length === 3) {
            sendJson(res, 200, engine.getProjectBriefRuns(projectId));
            return;
          }

          if (req.method === "GET" && path.length === 4 && path[3] === "latest") {
            const briefRun = engine.getLatestProjectBriefRun(projectId);
            if (!briefRun) {
              sendError(res, 404, `Project brief run not found: latest`);
              return;
            }
            sendJson(res, 200, briefRun);
            return;
          }

          if (req.method === "GET" && path.length === 4) {
            const briefRunId = decodeURIComponent(path[3]);
            const briefRun = engine.getProjectBriefRun(projectId, briefRunId);
            if (!briefRun) {
              sendError(res, 404, `Project brief run not found: ${briefRunId}`);
              return;
            }
            sendJson(res, 200, briefRun);
            return;
          }
        }
      }

      if (path.length >= 2 && path[0] === "tasks") {
        const taskId = decodeURIComponent(path[1]);
        const task = requireTask(engine, taskId);
        if (!task) {
          sendError(res, 404, `Task not found: ${taskId}`);
          return;
        }

        if (req.method === "GET" && path.length === 2) {
          sendJson(res, 200, task);
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "state") {
          const state = engine.getTaskState(taskId);
          if (!state) {
            sendError(res, 404, `No state for task: ${taskId}`);
            return;
          }
          sendJson(res, 200, state);
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "history") {
          sendJson(res, 200, engine.getDerivationHistory(taskId));
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "artifacts") {
          sendJson(res, 200, engine.getArtifacts(taskId));
          return;
        }

        if (req.method === "POST" && path.length === 3 && path[2] === "assignments") {
          const body = await readJsonBody(req);
          validator.assertValid(CONTRACT_IDS.assignmentCreate, body);
          const assignment = engine.createAssignment(taskId, body as AssignmentCreate);
          sendJson(res, 201, assignment);
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "assignments") {
          sendJson(res, 200, engine.getAssignments(taskId));
          return;
        }

        if (req.method === "POST" && path.length === 3 && path[2] === "messages") {
          const body = await readJsonBody(req);
          validator.assertValid(CONTRACT_IDS.taskMessageCreate, body);
          sendJson(res, 201, engine.createTaskMessage(taskId, body as TaskMessageCreate));
          return;
        }

        if (req.method === "GET" && path.length === 3 && path[2] === "messages") {
          sendJson(res, 200, engine.getTaskMessages(taskId));
          return;
        }
      }

      sendError(res, 404, `Route not found: ${req.method} ${url.pathname}`);
    } catch (err) {
      const mapped = mapMutationError(err);
      sendError(res, mapped.statusCode, mapped.message);
    }
  });
}

export async function listenArtifactLoopServer(options: ListenOptions): Promise<Server> {
  const server = createArtifactLoopServer(options);
  await new Promise<void>((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(options.port, options.host, () => {
      server.off("error", rejectListen);
      resolveListen();
    });
  });
  return server;
}
