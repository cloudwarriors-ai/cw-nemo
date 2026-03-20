// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { createProgram } from "../../cli/cli.js";
import { createEngine, type ArtifactLoopEngine } from "../../engine.js";
import { createArtifactLoopServer } from "../../service/server.js";
import type {
  CanonicalStatus,
  InboxItem,
  ProjectBrief,
  ProjectBriefRun,
  ProjectBriefSchedule,
  ProjectSummary,
  ProjectTaskListItem,
  ProjectWorkerSummary,
  Task,
  TaskDraftSet,
  TaskMessage,
  TaskState,
  Worker,
} from "../../types.js";

type HarnessMode = "in_process" | "subprocess";

interface CommandResult {
  argv: string[];
  stdout: string;
  stderr: string;
  exitCode: number;
}

interface ActorRegistrationInput {
  workerId: string;
  displayName: string;
  role: string;
  timezone: string;
  agentId: string;
  agentLabel: string;
  connectorType: string;
}

interface ProjectDefinitionInput {
  id: string;
  teamId: string;
  title: string;
  description: string;
  ownerWorkerId: string;
  goal: string;
  scope?: readonly string[];
  deliverables?: readonly string[];
  constraints?: readonly string[];
  definitionOfDone: string;
}

interface PingInput {
  taskId: string;
  fromWorkerId: string;
  fromAgentId?: string;
  toWorkerId: string;
  toAgentId?: string;
  body: string;
  kind?: "ping" | "reply" | "note";
}

interface ServiceHandle {
  url: string;
  dataDir: string;
  server?: Server;
  process?: ChildProcess;
}

interface HarnessPaths {
  rootDir: string;
  serviceDataDir: string;
  leadDataDir: string;
  workerDataDirs: Record<string, string>;
}

interface ActionContext {
  projectId?: string;
  taskId?: string;
  agentId?: string;
  workerId?: string;
}

interface OrgLoopHarnessOptions {
  mode?: HarnessMode;
  cwd?: string;
}

interface OrgLoopHarness {
  readonly mode: HarnessMode;
  readonly service: ServiceHandle;
  readonly lead: LeadHarnessActor;
  readonly workers: Map<string, WorkerHarnessActor>;
  readonly engine: ArtifactLoopEngine;
  readonly paths: HarnessPaths;
  readonly actionLog: CommandResult[];
  addWorker(input: ActorRegistrationInput): Promise<WorkerHarnessActor>;
  registerLead(input: ActorRegistrationInput): Promise<LeadHarnessActor>;
  getLatestDraftSet(projectId: string): TaskDraftSet | undefined;
  getOnlyProjectTask(projectId: string): Task | undefined;
  getProjectTasks(projectId: string): Task[];
  getLatestInboxItem(agentId: string): InboxItem | undefined;
  getLatestMessage(taskId: string): TaskMessage | undefined;
  getLatestBriefRun(projectId: string): ProjectBriefRun | undefined;
  getTaskState(taskId: string): TaskState | undefined;
  renderDiagnostics(context?: ActionContext): string;
  withDiagnostics<T>(label: string, context: ActionContext, fn: () => Promise<T>): Promise<T>;
  cleanup(): Promise<void>;
}

class HarnessError extends Error {}

function projectTaskToTask(task: ProjectTaskListItem): string {
  return `${task.id}:${task.status}:${task.assignee_human_id}${task.assignee_agent_id ? `/${task.assignee_agent_id}` : ""}`;
}

function buildProjectCreateArgs(input: ProjectDefinitionInput): string[] {
  const args = [
    "project", "create",
    "--id", input.id,
    "--team", input.teamId,
    "--title", input.title,
    "--description", input.description,
    "--owner-worker", input.ownerWorkerId,
    "--goal", input.goal,
    "--definition-of-done", input.definitionOfDone,
  ];
  for (const scope of input.scope ?? []) {
    args.push("--scope", scope);
  }
  for (const deliverable of input.deliverables ?? []) {
    args.push("--deliverable", deliverable);
  }
  for (const constraint of input.constraints ?? []) {
    args.push("--constraint", constraint);
  }
  return args;
}

function createCommandError(label: string, result: CommandResult, diagnostics: string): HarnessError {
  return new HarnessError(
    `${label} failed (exit=${result.exitCode})\n` +
      `argv: ${result.argv.join(" ")}\n` +
      `stdout:\n${result.stdout || "<empty>"}\n` +
      `stderr:\n${result.stderr || "<empty>"}\n` +
      `${diagnostics}`,
  );
}

async function getFreePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolveListen) => {
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  await new Promise<void>((resolveClose, rejectClose) => {
    server.close((err) => (err ? rejectClose(err) : resolveClose()));
  });
  return port;
}

async function waitForHealth(url: string, timeoutMs = 10_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError = "service not ready";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${url}/health`);
      if (response.ok) return;
      lastError = `health returned ${response.status}`;
    } catch (err) {
      lastError = (err as Error).message;
    }
    await new Promise((resolveSleep) => setTimeout(resolveSleep, 100));
  }
  throw new Error(`Timed out waiting for service health at ${url}: ${lastError}`);
}

async function startInProcessService(dataDir: string): Promise<ServiceHandle> {
  const port = await getFreePort();
  const server = createArtifactLoopServer({ dataDir });
  await new Promise<void>((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(port, "127.0.0.1", () => {
      server.off("error", rejectListen);
      resolveListen();
    });
  });
  return {
    url: `http://127.0.0.1:${port}`,
    dataDir,
    server,
  };
}

async function startSubprocessService(repoRoot: string, dataDir: string): Promise<ServiceHandle> {
  const port = await getFreePort();
  const child = spawn(
    process.execPath,
    ["bin/artifact-loop.js", "serve", "--host", "127.0.0.1", "--port", String(port), "--data-dir", dataDir],
    {
      cwd: repoRoot,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  child.stdout?.on("data", () => {});
  child.stderr?.on("data", () => {});
  const url = `http://127.0.0.1:${port}`;
  await waitForHealth(url);
  return {
    url,
    dataDir,
    process: child,
  };
}

async function stopService(service: ServiceHandle): Promise<void> {
  if (service.server) {
    await new Promise<void>((resolveClose, rejectClose) => {
      service.server!.close((err) => (err ? rejectClose(err) : resolveClose()));
    });
  }
  if (service.process) {
    service.process.kill("SIGTERM");
    await new Promise<void>((resolveDone) => {
      service.process!.once("exit", () => resolveDone());
      setTimeout(() => resolveDone(), 3_000);
    });
  }
}

class InProcessCommandRunner {
  async run(argv: string[], env: Record<string, string | undefined> = {}): Promise<CommandResult> {
    const stdoutChunks: string[] = [];
    const stderrChunks: string[] = [];
    const logs: string[] = [];
    const errors: string[] = [];
    const previousEnv = new Map<string, string | undefined>();
    const previousExitCode = process.exitCode;

    for (const [key, value] of Object.entries(env)) {
      previousEnv.set(key, process.env[key]);
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }

    vi.spyOn(process.stdout, "write").mockImplementation(((chunk: string | Uint8Array) => {
      stdoutChunks.push(String(chunk));
      return true;
    }) as typeof process.stdout.write);
    vi.spyOn(process.stderr, "write").mockImplementation(((chunk: string | Uint8Array) => {
      stderrChunks.push(String(chunk));
      return true;
    }) as typeof process.stderr.write);
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => {
      logs.push(args.map(String).join(" "));
    });
    vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
      errors.push(args.map(String).join(" "));
    });

    try {
      const program = createProgram();
      await program.parseAsync(["node", "artifact-loop", ...argv]);
    } finally {
      vi.restoreAllMocks();
      for (const [key, value] of previousEnv.entries()) {
        if (value === undefined) {
          delete process.env[key];
        } else {
          process.env[key] = value;
        }
      }
    }

    const exitCode = Number(process.exitCode ?? 0);
    process.exitCode = previousExitCode;

    const stdout = [stdoutChunks.join(""), logs.join("\n")].filter(Boolean).join("\n").trim();
    const stderr = [stderrChunks.join(""), errors.join("\n")].filter(Boolean).join("\n").trim();
    return { argv, stdout, stderr, exitCode };
  }
}

class SubprocessCommandRunner {
  constructor(private readonly repoRoot: string) {}

  async run(argv: string[], env: Record<string, string | undefined> = {}): Promise<CommandResult> {
    return new Promise<CommandResult>((resolveResult, rejectResult) => {
      const child = spawn(process.execPath, ["bin/artifact-loop.js", ...argv], {
        cwd: this.repoRoot,
        env: {
          ...process.env,
          ...Object.fromEntries(Object.entries(env).filter(([, value]) => value !== undefined)),
        },
        stdio: ["ignore", "pipe", "pipe"],
      });

      const stdoutChunks: Buffer[] = [];
      const stderrChunks: Buffer[] = [];
      child.stdout?.on("data", (chunk) => stdoutChunks.push(Buffer.from(chunk)));
      child.stderr?.on("data", (chunk) => stderrChunks.push(Buffer.from(chunk)));
      child.once("error", rejectResult);
      child.once("close", (code) => {
        resolveResult({
          argv,
          stdout: Buffer.concat(stdoutChunks).toString("utf-8").trim(),
          stderr: Buffer.concat(stderrChunks).toString("utf-8").trim(),
          exitCode: code ?? 0,
        });
      });
    });
  }
}

class HarnessRuntime {
  readonly actionLog: CommandResult[] = [];

  constructor(
    readonly mode: HarnessMode,
    readonly repoRoot: string,
    readonly service: ServiceHandle,
    readonly engine: ArtifactLoopEngine,
    private readonly runner: InProcessCommandRunner | SubprocessCommandRunner,
  ) {}

  async run(argv: string[], env: Record<string, string | undefined> = {}): Promise<CommandResult> {
    const result = await this.runner.run(argv, env);
    this.actionLog.push(result);
    return result;
  }
}

abstract class BaseHarnessActor {
  constructor(
    protected readonly harness: OrgLoopHarnessImpl,
    readonly workerId: string,
    readonly agentId: string,
    readonly dataDir: string,
  ) {}

  protected async runCli(
    argv: string[],
    opts: { remote?: boolean; json?: boolean; env?: Record<string, string | undefined> } = {},
  ): Promise<CommandResult> {
    const args = [...argv];
    const sentinelIndex = args.indexOf("--");
    const optionInsertIndex = sentinelIndex >= 0 ? sentinelIndex : args.length;
    if (opts.json && !args.includes("--json")) {
      args.splice(optionInsertIndex, 0, "--json");
    }
    if (!args.includes("--data-dir")) {
      args.splice(sentinelIndex >= 0 ? args.indexOf("--") : args.length, 0, "--data-dir", this.dataDir);
    }
    if (opts.remote && !args.includes("--service-url")) {
      args.splice(args.indexOf("--") >= 0 ? args.indexOf("--") : args.length, 0, "--service-url", this.harness.service.url);
    }
    const result = await this.harness.runtime.run(args, opts.env);
    if (result.exitCode !== 0) {
      throw createCommandError(
        `CLI action for ${this.workerId}`,
        result,
        this.harness.renderDiagnostics({ workerId: this.workerId }),
      );
    }
    return result;
  }

  protected parseJson<T>(result: CommandResult): T {
    const raw = result.stdout.trim();
    if (!raw) {
      throw new HarnessError(`Expected JSON output for ${result.argv.join(" ")}, received empty output`);
    }
    return JSON.parse(raw) as T;
  }

  async registerSelf(input: Omit<ActorRegistrationInput, "workerId" | "agentId">): Promise<Worker> {
    await this.runCli([
      "worker", "create",
      "--id", this.workerId,
      "--name", input.displayName,
      "--role", input.role,
      "--timezone", input.timezone,
    ], { remote: true });
    await this.runCli([
      "worker", "add-agent", this.workerId,
      "--id", this.agentId,
      "--label", input.agentLabel,
      "--connector", input.connectorType,
    ], { remote: true });
    return this.harness.engine.getWorker(this.workerId)!;
  }

  async registerAgent(label: string, connectorType: string): Promise<void> {
    await this.runCli([
      "worker", "add-agent", this.workerId,
      "--id", this.agentId,
      "--label", label,
      "--connector", connectorType,
    ], { remote: true });
  }

  async readInbox(status = "pending"): Promise<InboxItem[]> {
    const result = await this.runCli([
      "worker", "inbox",
      "--agent", this.agentId,
      "--status", status,
    ], { remote: true, json: true });
    return this.parseJson<InboxItem[]>(result);
  }

  async ackInbox(inboxItemId: string): Promise<InboxItem> {
    const result = await this.runCli([
      "worker", "inbox-ack", inboxItemId,
    ], { remote: true, json: true });
    return this.parseJson<InboxItem>(result);
  }

  async readMessages(taskId: string): Promise<TaskMessage[]> {
    const result = await this.runCli([
      "worker", "messages",
      "--task", taskId,
      "--agent", this.agentId,
    ], { remote: true, json: true });
    return this.parseJson<TaskMessage[]>(result);
  }

  async ackMessage(messageId: string): Promise<TaskMessage> {
    const result = await this.runCli([
      "task", "message-ack", messageId,
    ], { remote: true, json: true });
    return this.parseJson<TaskMessage>(result);
  }

  async useTask(taskId: string): Promise<void> {
    await this.runCli(["task", "use", taskId], { remote: false });
  }

  async runNext(taskId: string, command: string[], opts: { viaSession?: boolean } = {}): Promise<CommandResult> {
    if (opts.viaSession) {
      await this.useTask(taskId);
      return this.runCli([
        "run",
        "--next",
        "--worker", this.workerId,
        "--worker-agent", this.agentId,
        "--",
        ...command,
      ], { remote: true });
    }

    return this.runCli([
      "run",
      "--task", taskId,
      "--next",
      "--worker", this.workerId,
      "--worker-agent", this.agentId,
      "--",
      ...command,
    ], { remote: true });
  }
}

class LeadHarnessActor extends BaseHarnessActor {
  readonly homeTeamId = "team-core";

  async bootstrapOrg(input: Omit<ActorRegistrationInput, "workerId" | "agentId">): Promise<void> {
    await this.runCli([
      "org", "bootstrap",
      "--org-id", "org-core",
      "--org-name", "Core Org",
      "--org-timezone", input.timezone,
      "--team-id", this.homeTeamId,
      "--team-name", "Core Team",
      "--team-description", "Harness team",
      "--member-id", this.workerId,
      "--member-name", input.displayName,
      "--member-timezone", input.timezone,
      "--agent-id", this.agentId,
      "--agent-label", input.agentLabel,
      "--agent-connector", input.connectorType,
    ], { remote: true });
  }

  async createProject(input: ProjectDefinitionInput): Promise<void> {
    await this.runCli(buildProjectCreateArgs(input), { remote: true });
  }

  async addMemberToHomeTeam(input: ActorRegistrationInput): Promise<void> {
    await this.runCli([
      "team", "add-member", this.homeTeamId,
      "--member", input.workerId,
      "--role", input.role,
      "--by", this.workerId,
      "--name", input.displayName,
      "--timezone", input.timezone,
      "--worker-role", input.role,
    ], { remote: true });
  }

  async generateDrafts(projectId: string): Promise<TaskDraftSet> {
    const result = await this.runCli([
      "project", "generate-drafts", projectId,
      "--agent", this.agentId,
    ], { remote: true, json: true });
    return this.parseJson<TaskDraftSet>(result);
  }

  async listDraftSets(projectId: string): Promise<TaskDraftSet[]> {
    const result = await this.runCli([
      "project", "draft-sets", projectId,
    ], { remote: true, json: true });
    return this.parseJson<TaskDraftSet[]>(result);
  }

  async approveDrafts(projectId: string, draftSetId: string): Promise<{ draftSet: TaskDraftSet; tasks: Task[] }> {
    const result = await this.runCli([
      "project", "approve-drafts", projectId, draftSetId,
      "--by", this.workerId,
    ], { remote: true, json: true });
    return this.parseJson<{ draftSet: TaskDraftSet; tasks: Task[] }>(result);
  }

  async rejectDrafts(projectId: string, draftSetId: string): Promise<TaskDraftSet> {
    const result = await this.runCli([
      "project", "reject-drafts", projectId, draftSetId,
      "--by", this.workerId,
    ], { remote: true, json: true });
    return this.parseJson<TaskDraftSet>(result);
  }

  async assignTask(taskId: string, workerId: string, agentId?: string): Promise<void> {
    const args = [
      "task", "assign", taskId,
      "--worker", workerId,
      "--by", this.workerId,
    ];
    if (agentId) {
      args.push("--agent", agentId);
    }
    await this.runCli(args, { remote: true });
  }

  async pingTask(input: PingInput): Promise<TaskMessage> {
    const args = [
      "task", "ping", input.taskId,
      "--from-worker", input.fromWorkerId,
      "--to-worker", input.toWorkerId,
      "--body", input.body,
      "--kind", input.kind ?? "ping",
    ];
    if (input.fromAgentId) args.push("--from-agent", input.fromAgentId);
    if (input.toAgentId) args.push("--to-agent", input.toAgentId);
    const result = await this.runCli(args, { remote: true, json: true });
    return this.parseJson<TaskMessage>(result);
  }

  async scheduleBrief(projectId: string, timezone = "America/New_York", deliveryHour = 9): Promise<ProjectBriefSchedule> {
    const result = await this.runCli([
      "project", "schedule-brief", projectId,
      "--owner-worker", this.workerId,
      "--timezone", timezone,
      "--delivery-hour", String(deliveryHour),
    ], { remote: true, json: true });
    return this.parseJson<ProjectBriefSchedule>(result);
  }

  async readProjectSummary(projectId: string): Promise<ProjectSummary> {
    const result = await this.runCli(["project", "summary", projectId], { remote: true, json: true });
    return this.parseJson<ProjectSummary>(result);
  }

  async readProjectWorkers(projectId: string): Promise<ProjectWorkerSummary> {
    const result = await this.runCli(["project", "workers", projectId], { remote: true, json: true });
    return this.parseJson<ProjectWorkerSummary>(result);
  }

  async readBrief(projectId: string, mode: "current" | "latest-run" | "history" = "current"): Promise<ProjectBrief | ProjectBriefRun | ProjectBriefRun[]> {
    const args = ["project", "brief", projectId];
    if (mode === "latest-run") {
      args.push("--latest-run");
    } else if (mode === "history") {
      args.push("--history");
    }
    const result = await this.runCli(args, { remote: true, json: true });
    return this.parseJson<ProjectBrief | ProjectBriefRun | ProjectBriefRun[]>(result);
  }

  async runScheduledBriefs(): Promise<{ generated_count: number; generated_project_ids: string[] }> {
    const result = await this.runCli([
      "run-scheduled-briefs",
      "--data-dir", this.harness.paths.serviceDataDir,
    ], { remote: false, json: true });
    return this.parseJson<{ generated_count: number; generated_project_ids: string[] }>(result);
  }
}

class WorkerHarnessActor extends BaseHarnessActor {}

class OrgLoopHarnessImpl implements OrgLoopHarness {
  readonly workers = new Map<string, WorkerHarnessActor>();
  readonly lead: LeadHarnessActor;
  readonly actionLog: CommandResult[];

  constructor(
    readonly mode: HarnessMode,
    readonly runtime: HarnessRuntime,
    readonly service: ServiceHandle,
    readonly engine: ArtifactLoopEngine,
    readonly paths: HarnessPaths,
  ) {
    this.actionLog = runtime.actionLog;
    this.lead = new LeadHarnessActor(this, "lead-1", "lead-agent-1", this.paths.leadDataDir);
  }

  async registerLead(input: ActorRegistrationInput): Promise<LeadHarnessActor> {
    if (input.workerId !== this.lead.workerId || input.agentId !== this.lead.agentId) {
      throw new HarnessError(`Lead actor is fixed to ${this.lead.workerId}/${this.lead.agentId} in this harness`);
    }
    await this.lead.bootstrapOrg({
      displayName: input.displayName,
      role: input.role,
      timezone: input.timezone,
      agentLabel: input.agentLabel,
      connectorType: input.connectorType,
    });
    return this.lead;
  }

  async addWorker(input: ActorRegistrationInput): Promise<WorkerHarnessActor> {
    const dataDir = this.paths.workerDataDirs[input.workerId] ?? join(this.paths.rootDir, input.workerId);
    this.paths.workerDataDirs[input.workerId] = dataDir;
    const actor = new WorkerHarnessActor(this, input.workerId, input.agentId, dataDir);
    await this.lead.addMemberToHomeTeam(input);
    await actor.registerAgent(input.agentLabel, input.connectorType);
    this.workers.set(input.workerId, actor);
    return actor;
  }

  getLatestDraftSet(projectId: string): TaskDraftSet | undefined {
    return this.engine.getTaskDraftSets(projectId).at(-1);
  }

  getProjectTasks(projectId: string): Task[] {
    return this.engine.getProjectTasks(projectId);
  }

  getOnlyProjectTask(projectId: string): Task | undefined {
    const tasks = this.getProjectTasks(projectId);
    if (tasks.length !== 1) {
      throw new HarnessError(`Expected exactly one task for ${projectId}, found ${tasks.length}`);
    }
    return tasks[0];
  }

  getLatestInboxItem(agentId: string): InboxItem | undefined {
    return this.engine.getWorkerAgentInbox(agentId)[0];
  }

  getLatestMessage(taskId: string): TaskMessage | undefined {
    return this.engine.getTaskMessages(taskId).at(-1);
  }

  getLatestBriefRun(projectId: string): ProjectBriefRun | undefined {
    return this.engine.getLatestProjectBriefRun(projectId);
  }

  getTaskState(taskId: string): TaskState | undefined {
    return this.engine.getTaskState(taskId);
  }

  renderDiagnostics(context: ActionContext = {}): string {
    const lines: string[] = ["Diagnostics:"];
    const recent = this.actionLog.slice(-6);
    lines.push("Recent commands:");
    if (recent.length === 0) {
      lines.push("  none");
    } else {
      for (const entry of recent) {
        lines.push(`  - ${entry.argv.join(" ")} [exit=${entry.exitCode}]`);
        if (entry.stdout) lines.push(`    stdout: ${entry.stdout.replace(/\n/g, " | ")}`);
        if (entry.stderr) lines.push(`    stderr: ${entry.stderr.replace(/\n/g, " | ")}`);
      }
    }

    if (context.taskId) {
      lines.push(`Task state: ${JSON.stringify(this.engine.getTaskState(context.taskId) ?? null)}`);
      const messages = this.engine.getTaskMessages(context.taskId).map((message) => ({
        id: message.id,
        kind: message.kind,
        body: message.body,
        acknowledged_at: message.acknowledged_at,
      }));
      lines.push(`Messages: ${JSON.stringify(messages)}`);
    }
    if (context.agentId) {
      const inbox = this.engine.getWorkerAgentInbox(context.agentId).map((item) => ({
        id: item.id,
        kind: item.kind,
        status: item.status,
        task_id: item.task_id,
        payload_ref: item.payload_ref,
      }));
      lines.push(`Inbox: ${JSON.stringify(inbox)}`);
    }
    if (context.projectId) {
      const summary = this.engine.getProjectSummary(context.projectId);
      const workerSummary = this.engine.getProjectWorkerSummary(context.projectId);
      const latestBrief = this.engine.getLatestProjectBriefRun(context.projectId);
      lines.push(`Project summary: ${JSON.stringify({
        total_tasks: summary.total_tasks,
        counts_by_status: summary.counts_by_status,
        blocked: summary.buckets.blocked.map(projectTaskToTask),
        needs_input: summary.buckets.needs_input.map(projectTaskToTask),
        ready_for_review: summary.buckets.ready_for_review.map(projectTaskToTask),
      })}`);
      lines.push(`Project workers: ${JSON.stringify({
        by_human: workerSummary.by_human.map((group) => ({
          assignee_human_id: group.assignee_human_id,
          tasks: group.tasks.map(projectTaskToTask),
        })),
        by_agent: workerSummary.by_agent.map((group) => ({
          assignee_agent_id: group.assignee_agent_id,
          tasks: group.tasks.map(projectTaskToTask),
        })),
      })}`);
      lines.push(`Latest brief run: ${JSON.stringify(latestBrief ? {
        id: latestBrief.id,
        generated_at: latestBrief.generated_at,
        project_id: latestBrief.project_id,
      } : null)}`);
    }
    return lines.join("\n");
  }

  async withDiagnostics<T>(label: string, context: ActionContext, fn: () => Promise<T>): Promise<T> {
    try {
      return await fn();
    } catch (err) {
      if (err instanceof Error) {
        throw new HarnessError(`${label} failed\n${err.message}\n${this.renderDiagnostics(context)}`);
      }
      throw err;
    }
  }

  async cleanup(): Promise<void> {
    await stopService(this.service);
    rmSync(this.paths.rootDir, { recursive: true, force: true });
  }
}

export async function createOrgLoopHarness(options: OrgLoopHarnessOptions = {}): Promise<OrgLoopHarness> {
  const mode = options.mode ?? "in_process";
  const repoRoot = resolve(options.cwd ?? process.cwd());
  const rootDir = mkdtempSync(join(tmpdir(), `artifact-loop-harness-${mode}-`));
  const serviceDataDir = join(rootDir, "service-data");
  const leadDataDir = join(rootDir, "lead-data");
  const workerDataDirs: Record<string, string> = {};

  const service = mode === "subprocess"
    ? await startSubprocessService(repoRoot, serviceDataDir)
    : await startInProcessService(serviceDataDir);
  const engine = createEngine({ dataDir: serviceDataDir });
  const runner = mode === "subprocess"
    ? new SubprocessCommandRunner(repoRoot)
    : new InProcessCommandRunner();
  return new OrgLoopHarnessImpl(
    mode,
    new HarnessRuntime(mode, repoRoot, service, engine, runner),
    service,
    engine,
    {
      rootDir,
      serviceDataDir,
      leadDataDir,
      workerDataDirs,
    },
  );
}

export async function expectHarnessScenario<T>(
  harness: OrgLoopHarness,
  label: string,
  context: ActionContext,
  fn: () => Promise<T>,
): Promise<T> {
  return harness.withDiagnostics(label, context, fn);
}

export type {
  HarnessMode,
  OrgLoopHarness,
  ActorRegistrationInput,
  ProjectDefinitionInput,
  PingInput,
};
