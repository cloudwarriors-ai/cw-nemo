// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createProgram } from "../../cli/cli.js";
import { setSession, getSession } from "../../cli/helpers/session.js";
import { buildContext } from "../../cli/helpers/context.js";
import { buildRawArtifact } from "../../cli/helpers/raw-artifact.js";
import { createEngine } from "../../engine.js";
import { createArtifactLoopServer } from "../../service/server.js";
import type { TaskCreate, TestResultPayload } from "../../types.js";

let serviceDataDir: string;
let workerDataDir: string;
let server: Server | undefined;
let serviceUrl = "";

function makeTask(id = "feat-remote", overrides?: Partial<TaskCreate>): TaskCreate {
  return {
    id,
    title: id,
    description: `${id} task`,
    assignee_human_id: "chad",
    status: "not_started",
    acceptance_criteria: "tests pass",
    acceptance_signals: [
      { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
    ],
    depends_on: [],
    ...overrides,
  };
}

async function listen(serverToStart: Server): Promise<string> {
  await new Promise<void>((resolveListen) => {
    serverToStart.listen(0, "127.0.0.1", resolveListen);
  });
  const address = serverToStart.address() as AddressInfo;
  return `http://127.0.0.1:${address.port}`;
}

async function requestService<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${serviceUrl}${path}`, init);
  return response.json() as Promise<T>;
}

async function bootstrapServiceOrg(): Promise<void> {
  await requestService("/org/bootstrap", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      organization: {
        id: "org-core",
        name: "Core Org",
        timezone: "America/New_York",
      },
      initial_team: {
        id: "team-core",
        name: "Core Team",
        description: "Primary test team",
      },
      initial_member: {
        id: "lead-1",
        display_name: "Lead One",
        timezone: "America/New_York",
      },
      initial_agent: {
        id: "lead-agent-1",
        label: "Lead Agent",
        connector_type: "lead-cli",
      },
    }),
  });
}

async function addServiceMember(
  memberId: string,
  role: "admin" | "lead" | "worker",
  displayName: string,
): Promise<void> {
  await requestService("/teams/team-core/members", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      member_id: memberId,
      role,
      display_name: displayName,
      timezone: "America/New_York",
      added_by_worker_id: "lead-1",
      worker_role: role,
    }),
  });
}

async function runCliAsync(
  args: string[],
  env: Record<string, string | undefined> = {},
): Promise<{ stdout: string; stderr: string; logs: string }> {
  const stdout: string[] = [];
  const stderr: string[] = [];
  const logs: string[] = [];
  const previousEnv = new Map<string, string | undefined>();

  for (const [key, value] of Object.entries(env)) {
    previousEnv.set(key, process.env[key]);
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }

  vi.spyOn(process.stdout, "write").mockImplementation(((chunk: string | Uint8Array) => {
    stdout.push(String(chunk));
    return true;
  }) as typeof process.stdout.write);
  vi.spyOn(process.stderr, "write").mockImplementation(((chunk: string | Uint8Array) => {
    stderr.push(String(chunk));
    return true;
  }) as typeof process.stderr.write);
  vi.spyOn(console, "log").mockImplementation((...a: unknown[]) => logs.push(String(a[0])));
  vi.spyOn(console, "error").mockImplementation((...a: unknown[]) => stderr.push(String(a[0])));

  const program = createProgram();
  await program.parseAsync(["node", "test", ...args]);

  vi.restoreAllMocks();
  for (const [key, value] of previousEnv.entries()) {
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }

  return {
    stdout: stdout.join(""),
    stderr: stderr.join(""),
    logs: logs.join("\n"),
  };
}

beforeEach(async () => {
  serviceDataDir = mkdtempSync(join(tmpdir(), "al-remote-service-"));
  workerDataDir = mkdtempSync(join(tmpdir(), "al-remote-worker-"));
  server = createArtifactLoopServer({ dataDir: serviceDataDir });
  serviceUrl = await listen(server);
});

afterEach(async () => {
  if (server) {
    await new Promise<void>((resolveClose, rejectClose) => {
      server!.close((err) => (err ? rejectClose(err) : resolveClose()));
    });
  }
  server = undefined;
  rmSync(serviceDataDir, { recursive: true, force: true });
  rmSync(workerDataDir, { recursive: true, force: true });
  process.exitCode = undefined;
  delete process.env.ARTIFACT_LOOP_SERVICE_URL;
  delete process.env.ARTIFACT_LOOP_WORKER_AGENT_ID;
});

describe("remote worker mode", () => {
  it("ingests test evidence through the shared service and persists remote provenance", async () => {
    const serviceEngine = createEngine({ dataDir: serviceDataDir });
    serviceEngine.createTask(makeTask());

    const result = await runCliAsync([
      "emit", "test",
      "--task", "feat-remote",
      "--signal-id", "sig-test",
      "--passed",
      "--worker", "worker-1",
      "--worker-agent", "agent-1",
      "--service-url", serviceUrl,
      "--data-dir", workerDataDir,
    ]);

    expect(result.logs).toContain("Emitted test_result (passed) for feat-remote");
    expect(serviceEngine.getTaskState("feat-remote")?.status).toBe("ready_for_review");
    const artifact = serviceEngine.getArtifacts("feat-remote")[0];
    expect(artifact?.artifact_source).toBe("remote_worker_connector");
    expect(artifact?.worker_id).toBe("worker-1");
    expect(artifact?.worker_agent_id).toBe("agent-1");
  });

  it("renders remote task status and history while keeping session resolution local", async () => {
    const serviceEngine = createEngine({ dataDir: serviceDataDir });
    const workerEngine = createEngine({ dataDir: workerDataDir });
    serviceEngine.createTask(makeTask("feat-status", {
      acceptance_signals: [
        { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        { id: "sig-merge", category: "merge", required: true, success_condition: "merged to main" },
      ],
    }));
    workerEngine.createTask(makeTask("feat-status", {
      acceptance_signals: [
        { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        { id: "sig-merge", category: "merge", required: true, success_condition: "merged to main" },
      ],
    }));
    setSession(workerDataDir, "feat-status");

    const payload: TestResultPayload = {
      type: "test_result",
      signal_id: "sig-test",
      passed: true,
    };
    serviceEngine.ingest(
      buildRawArtifact("test_result", payload, "Passing test", "remote_worker_connector"),
      buildContext({ task: "feat-status", worker: "worker-1" }),
    );

    const status = await runCliAsync([
      "task", "status",
      "--service-url", serviceUrl,
      "--data-dir", workerDataDir,
    ]);
    expect(status.logs).toContain("Task: feat-status (from session)");
    expect(status.logs).toContain("[sig-test] (test, required) satisfied");
    expect(status.logs).toContain("[sig-merge] (merge, required) not yet satisfied");
    expect(status.logs).toContain("artifact-loop emit merge --signal-id sig-merge --ref <ref> --branch <branch>");

    const historyJson = await runCliAsync([
      "task", "history", "feat-status",
      "--json",
      "--service-url", serviceUrl,
      "--data-dir", workerDataDir,
    ]);
    const parsed = JSON.parse(historyJson.logs);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].output_state).toBe("ready_for_review");
  });

  it("resolves run --next against remote task state and ingests remotely", async () => {
    const serviceEngine = createEngine({ dataDir: serviceDataDir });
    serviceEngine.createTask(makeTask("feat-next"));

    const result = await runCliAsync([
      "run",
      "--task", "feat-next",
      "--next",
      "--worker", "worker-2",
      "--worker-agent", "agent-2",
      "--service-url", serviceUrl,
      "--data-dir", workerDataDir,
      "--", "node", "-e", "console.log('remote next ok')",
    ]);

    expect(result.stdout).toContain("remote next ok");
    expect(result.logs).toContain("Using next signal: sig-test (test, required)");
    expect(result.logs).toContain("Emitted test_result (passed) for feat-next");
    expect(serviceEngine.getTaskState("feat-next")?.status).toBe("ready_for_review");
    const artifact = serviceEngine.getArtifacts("feat-next")[0];
    expect(artifact?.artifact_source).toBe("remote_worker_connector");
    expect(artifact?.worker_agent_id).toBe("agent-2");
  });

  it("uses env activation for remote mode and lets explicit flag override a bad env URL", async () => {
    const serviceEngine = createEngine({ dataDir: serviceDataDir });
    serviceEngine.createTask(makeTask("feat-env"));

    const viaEnv = await runCliAsync([
      "task", "status", "feat-env",
      "--data-dir", workerDataDir,
    ], {
      ARTIFACT_LOOP_SERVICE_URL: serviceUrl,
    });
    expect(viaEnv.logs).toContain("Task: feat-env");

    const viaExplicitFlag = await runCliAsync([
      "task", "status", "feat-env",
      "--service-url", serviceUrl,
      "--data-dir", workerDataDir,
    ], {
      ARTIFACT_LOOP_SERVICE_URL: "http://127.0.0.1:9",
    });
    expect(viaExplicitFlag.logs).toContain("Task: feat-env");
  });

  it("keeps task use local-only even when a bad remote env var is present", async () => {
    const workerEngine = createEngine({ dataDir: workerDataDir });
    workerEngine.createTask(makeTask("feat-local"));

    const result = await runCliAsync([
      "task", "use", "feat-local",
      "--data-dir", workerDataDir,
    ], {
      ARTIFACT_LOOP_SERVICE_URL: "http://127.0.0.1:9",
    });

    expect(result.logs).toContain("Now using task: feat-local");
    expect(getSession(workerDataDir)?.current_task_id).toBe("feat-local");
  });

  it("feeds project summaries through the existing remote worker flow after tasks are linked", async () => {
    await bootstrapServiceOrg();
    await addServiceMember("chad", "lead", "Chad");
    await addServiceMember("avery", "worker", "Avery");

    await requestService("/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "proj-core",
        title: "Core Project",
        description: "Lead-readable coordination surface",
        team_id: "team-core",
        owner_worker_id: "chad",
      }),
    });
    await requestService("/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(makeTask("feat-proj-ready", {
        assignee_agent_id: "agent-1",
        acceptance_signals: [
          { id: "sig-ready", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        ],
      })),
    });
    await requestService("/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(makeTask("feat-proj-blocked", {
        assignee_human_id: "avery",
        assignee_agent_id: "agent-2",
        acceptance_signals: [
          { id: "sig-blocked", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        ],
      })),
    });
    await requestService("/projects/proj-core/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_id: "feat-proj-ready" }),
    });
    await requestService("/projects/proj-core/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_id: "feat-proj-blocked" }),
    });

    await runCliAsync([
      "emit", "test",
      "--task", "feat-proj-ready",
      "--signal-id", "sig-ready",
      "--passed",
      "--worker", "worker-1",
      "--worker-agent", "agent-1",
      "--service-url", serviceUrl,
      "--data-dir", workerDataDir,
    ]);
    await runCliAsync([
      "emit", "test",
      "--task", "feat-proj-blocked",
      "--signal-id", "sig-blocked",
      "--failed",
      "--worker", "worker-2",
      "--worker-agent", "agent-2",
      "--service-url", serviceUrl,
      "--data-dir", workerDataDir,
    ]);

    const summary = await requestService<{
      total_tasks: number;
      counts_by_status: Record<string, number>;
      buckets: Record<string, Array<{ id: string }>>;
    }>("/projects/proj-core/summary");
    expect(summary.total_tasks).toBe(2);
    expect(summary.counts_by_status.ready_for_review).toBe(1);
    expect(summary.counts_by_status.blocked).toBe(1);
    expect(summary.buckets.ready_for_review.map((task) => task.id)).toEqual(["feat-proj-ready"]);
    expect(summary.buckets.blocked.map((task) => task.id)).toEqual(["feat-proj-blocked"]);

    const summaryCli = await runCliAsync([
      "project", "summary", "proj-core",
      "--service-url", serviceUrl,
      "--data-dir", workerDataDir,
    ]);
    expect(summaryCli.logs).toContain("Total tasks: 2");
    expect(summaryCli.logs).toContain("Blocked:");

    const workers = await requestService<{
      by_human: Array<{ assignee_human_id: string; tasks: Array<{ id: string }> }>;
      by_agent: Array<{ assignee_agent_id: string; tasks: Array<{ id: string }> }>;
    }>("/projects/proj-core/workers");
    expect(workers.by_human.map((group) => group.assignee_human_id)).toEqual(["avery", "chad"]);
    expect(workers.by_agent.map((group) => group.assignee_agent_id)).toEqual(["agent-1", "agent-2"]);

    const workersCli = await runCliAsync([
      "project", "workers", "proj-core",
      "--service-url", serviceUrl,
      "--data-dir", workerDataDir,
    ]);
    expect(workersCli.logs).toContain("By human:");
    expect(workersCli.logs).toContain("agent-1:");

    const brief = await requestService<{
      recent_movement: Array<{ task_id: string }>;
      by_worker: Array<{ worker_id: string; tasks: Array<{ id: string }> }>;
      lead_attention_items: Array<{ kind: string; task: { id: string } }>;
      rendered_text: string;
    }>("/projects/proj-core/brief");
    expect(brief.recent_movement.map((item) => item.task_id)).toEqual(["feat-proj-blocked", "feat-proj-ready"]);
    expect(brief.by_worker.map((group) => ({
      worker_id: group.worker_id,
      taskIds: group.tasks.map((task) => task.id),
    })).sort((a, b) => a.worker_id.localeCompare(b.worker_id))).toEqual([
      { worker_id: "worker-1", taskIds: ["feat-proj-ready"] },
      { worker_id: "worker-2", taskIds: ["feat-proj-blocked"] },
    ]);
    expect(brief.lead_attention_items.map((item) => item.kind)).toEqual(["blocked", "ready_for_review"]);
    expect(brief.rendered_text).toContain("Project Brief: Core Project (proj-core)");
    expect(brief.rendered_text).toContain("By worker:");
  });

  it("fails closed when remote ingest fails after the wrapped command succeeds", async () => {
    const failingServer = createServer((req, res) => {
      if (req.method === "GET" && req.url === "/tasks/feat-fail") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify(makeTask("feat-fail")));
        return;
      }
      if (req.method === "POST" && req.url === "/artifacts/ingest") {
        res.writeHead(500, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: "ingest rejected" }));
        return;
      }
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "not found" }));
    });
    const failingUrl = await listen(failingServer);

    try {
      const result = await runCliAsync([
        "run",
        "--task", "feat-fail",
        "--signal-id", "sig-test",
        "--service-url", failingUrl,
        "--data-dir", workerDataDir,
        "--", "node", "-e", "console.log('wrapped command ok')",
      ]);

      expect(result.stdout).toContain("wrapped command ok");
      expect(result.stderr).toContain("Remote service");
      expect(result.stderr).toContain("ingest rejected");
      expect(process.exitCode).toBe(1);
    } finally {
      await new Promise<void>((resolveClose, rejectClose) => {
        failingServer.close((err) => (err ? rejectClose(err) : resolveClose()));
      });
    }
  });
});
