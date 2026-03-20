// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AddressInfo } from "node:net";
import type { Server } from "node:http";
import { createArtifactLoopServer } from "../service/server.js";

let dataDir: string;
let server: Server | undefined;
let baseUrl = "";

async function request(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${baseUrl}${path}`, init);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init);
  return response.json() as Promise<T>;
}

async function bootstrapOrgFixture(): Promise<void> {
  const response = await request("/org/bootstrap", {
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
  expect(response.status).toBe(201);
}

async function addTeamMemberFixture(
  memberId: string,
  role: "admin" | "lead" | "worker",
  options: {
    displayName: string;
    timezone?: string;
    addedBy?: string;
    workerRole?: "admin" | "lead" | "worker";
  },
): Promise<void> {
  const response = await request("/teams/team-core/members", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      member_id: memberId,
      role,
      display_name: options.displayName,
      timezone: options.timezone ?? "America/New_York",
      added_by_worker_id: options.addedBy ?? "lead-1",
      worker_role: options.workerRole ?? role,
    }),
  });
  expect(response.status).toBe(201);
}

beforeEach(async () => {
  dataDir = mkdtempSync(join(tmpdir(), "al-service-"));
  server = createArtifactLoopServer({ dataDir });
  await new Promise<void>((resolveListen) => {
    server!.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address() as AddressInfo;
  baseUrl = `http://127.0.0.1:${address.port}`;
});

afterEach(async () => {
  if (server) {
    await new Promise<void>((resolveClose, rejectClose) => {
      server!.close((err) => (err ? rejectClose(err) : resolveClose()));
    });
  }
  server = undefined;
  rmSync(dataDir, { recursive: true, force: true });
});

describe("artifact-loop HTTP service", () => {
  it("serves health checks", async () => {
    const response = await requestJson<{ ok: boolean; service: string; data_dir: string }>("/health");
    expect(response.ok).toBe(true);
    expect(response.service).toBe("artifact-loop");
    expect(response.data_dir).toBe(dataDir);
  });

  it("creates tasks, assignments, ingests artifacts, and exposes state/history/stats", async () => {
    await request("/workers", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "chad",
        display_name: "Chad",
        role: "lead",
        timezone: "America/New_York",
      }),
    });
    await request("/workers", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "worker-agent-owner",
        display_name: "Worker Agent Owner",
        role: "worker",
        timezone: "America/New_York",
      }),
    });
    await request("/workers/chad/agents", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "worker-agent-1",
        label: "Worker Agent 1",
        connector_type: "remote",
      }),
    });

    const createResponse = await request("/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "feat-http",
        title: "HTTP Feature",
        description: "Shared coordination flow",
        assignee_human_id: "chad",
        status: "not_started",
        acceptance_criteria: "Passing test evidence exists",
        acceptance_signals: [
          { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        ],
        depends_on: [],
      }),
    });
    expect(createResponse.status).toBe(201);

    const task = await requestJson<{ id: string; assignee_human_id: string }>("/tasks/feat-http");
    expect(task.id).toBe("feat-http");
    expect(task.assignee_human_id).toBe("chad");

    const assignmentResponse = await request("/tasks/feat-http/assignments", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        assignee_human_id: "chad",
        assignee_agent_id: "worker-agent-1",
        assigned_by: "chad",
      }),
    });
    expect(assignmentResponse.status).toBe(201);

    const assignedTask = await requestJson<{ assignee_human_id: string; assignee_agent_id?: string }>("/tasks/feat-http");
    expect(assignedTask.assignee_human_id).toBe("chad");
    expect(assignedTask.assignee_agent_id).toBe("worker-agent-1");

    const filteredTasks = await requestJson<Array<{ id: string }>>("/tasks?assignee_agent_id=worker-agent-1");
    expect(filteredTasks.map((item) => item.id)).toEqual(["feat-http"]);

    const assignments = await requestJson<Array<{ task_id: string; assignee_agent_id?: string }>>("/tasks/feat-http/assignments");
    expect(assignments).toHaveLength(1);
    expect(assignments[0]?.task_id).toBe("feat-http");
    expect(assignments[0]?.assignee_agent_id).toBe("worker-agent-1");

    const ingestResponse = await request("/artifacts/ingest", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        artifact: {
          id: "ra-test-1",
          type: "test_result",
          timestamp: "2026-03-19T12:00:00.000Z",
          source: "worker-connector",
          pointer: "memory://test-run",
          summary: "Passing test evidence",
          raw_payload: {
            type: "test_result",
            signal_id: "sig-test",
            passed: true,
          },
        },
        context: {
          primary_task_id: "feat-http",
          session_id: "session-1",
          worker_id: "worker-1",
          worker_agent_id: "worker-agent-1",
          context_source: "explicit_lock",
        },
      }),
    });
    expect(ingestResponse.status).toBe(201);
    const ingestResult = await ingestResponse.json() as {
      normalizedArtifact: { worker_id: string; worker_agent_id?: string; context_source: string; artifact_source: string };
      derivationOutput: { nextState: { status: string } };
    };
    expect(ingestResult.normalizedArtifact.worker_id).toBe("worker-1");
    expect(ingestResult.normalizedArtifact.worker_agent_id).toBe("worker-agent-1");
    expect(ingestResult.normalizedArtifact.context_source).toBe("explicit_lock");
    expect(ingestResult.normalizedArtifact.artifact_source).toBe("worker-connector");
    expect(ingestResult.derivationOutput.nextState.status).toBe("ready_for_review");

    const artifacts = await requestJson<Array<{ artifact_source: string; worker_agent_id?: string }>>("/tasks/feat-http/artifacts");
    expect(artifacts).toHaveLength(1);
    expect(artifacts[0]?.artifact_source).toBe("worker-connector");
    expect(artifacts[0]?.worker_agent_id).toBe("worker-agent-1");

    const state = await requestJson<{ status: string }>("/tasks/feat-http/state");
    expect(state.status).toBe("ready_for_review");

    const history = await requestJson<Array<{ output_state: string }>>("/tasks/feat-http/history");
    expect(history).toHaveLength(1);
    expect(history[0]?.output_state).toBe("ready_for_review");

    const stats = await requestJson<{
      artifacts_by_type: Record<string, number>;
      evidence_buckets: Record<string, number>;
    }>("/stats");
    expect(stats.artifacts_by_type.test_result).toBe(1);
    expect(stats.evidence_buckets.automatic_any).toBe(1);
  });

  it("creates projects, links tasks, and exposes project summaries and worker grouping", async () => {
    await bootstrapOrgFixture();
    await addTeamMemberFixture("chad", "lead", { displayName: "Chad" });
    await addTeamMemberFixture("avery", "worker", { displayName: "Avery" });

    const projectResponse = await request("/projects", {
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
    expect(projectResponse.status).toBe(201);

    await request("/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "feat-ready",
        title: "Ready Task",
        description: "Shared coordination flow",
        assignee_human_id: "chad",
        assignee_agent_id: "agent-1",
        status: "not_started",
        acceptance_criteria: "Passing test evidence exists",
        acceptance_signals: [
          { id: "sig-ready", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        ],
        depends_on: [],
      }),
    });
    await request("/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "feat-blocked",
        title: "Blocked Task",
        description: "Shared coordination flow",
        assignee_human_id: "avery",
        assignee_agent_id: "agent-2",
        status: "not_started",
        acceptance_criteria: "Passing test evidence exists",
        acceptance_signals: [
          { id: "sig-blocked", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        ],
        depends_on: [],
      }),
    });

    const readyLink = await request("/projects/proj-core/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_id: "feat-ready" }),
    });
    expect(readyLink.status).toBe(200);
    expect(((await readyLink.json()) as { project_id?: string }).project_id).toBe("proj-core");

    const sameLink = await request("/projects/proj-core/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_id: "feat-ready" }),
    });
    expect(sameLink.status).toBe(200);

    const blockedLink = await request("/projects/proj-core/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_id: "feat-blocked" }),
    });
    expect(blockedLink.status).toBe(200);

    await request("/artifacts/ingest", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        artifact: {
          id: "ra-test-ready",
          type: "test_result",
          timestamp: "2026-03-19T12:00:00.000Z",
          source: "worker-connector",
          pointer: "memory://test-run",
          summary: "Passing test evidence",
          raw_payload: {
            type: "test_result",
            signal_id: "sig-ready",
            passed: true,
          },
        },
        context: {
          primary_task_id: "feat-ready",
          session_id: "session-1",
          worker_id: "worker-1",
          worker_agent_id: "agent-1",
          context_source: "explicit_lock",
        },
      }),
    });
    await request("/artifacts/ingest", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        artifact: {
          id: "ra-test-blocked",
          type: "test_result",
          timestamp: "2026-03-19T12:01:00.000Z",
          source: "worker-connector",
          pointer: "memory://test-run",
          summary: "Failing test evidence",
          raw_payload: {
            type: "test_result",
            signal_id: "sig-blocked",
            passed: false,
          },
        },
        context: {
          primary_task_id: "feat-blocked",
          session_id: "session-1",
          worker_id: "worker-2",
          worker_agent_id: "agent-2",
          context_source: "explicit_lock",
        },
      }),
    });

    const project = await requestJson<{ id: string; title: string }>("/projects/proj-core");
    expect(project.id).toBe("proj-core");
    expect(project.title).toBe("Core Project");

    const projectTasks = await requestJson<Array<{ id: string; project_id?: string }>>("/projects/proj-core/tasks");
    expect(projectTasks.map((task) => task.id)).toEqual(["feat-blocked", "feat-ready"]);
    expect(projectTasks.every((task) => task.project_id === "proj-core")).toBe(true);

    const filteredProjectTasks = await requestJson<Array<{ id: string }>>("/projects/proj-core/tasks?assignee_agent_id=agent-1");
    expect(filteredProjectTasks.map((task) => task.id)).toEqual(["feat-ready"]);

    const filteredTasks = await requestJson<Array<{ id: string }>>("/tasks?project_id=proj-core");
    expect(filteredTasks.map((task) => task.id)).toEqual(["feat-blocked", "feat-ready"]);

    const summary = await requestJson<{
      total_tasks: number;
      counts_by_status: Record<string, number>;
      buckets: Record<string, Array<{ id: string }>>;
      last_activity_at: string | null;
    }>("/projects/proj-core/summary");
    expect(summary.total_tasks).toBe(2);
    expect(summary.counts_by_status.ready_for_review).toBe(1);
    expect(summary.counts_by_status.blocked).toBe(1);
    expect(summary.buckets.ready_for_review.map((task) => task.id)).toEqual(["feat-ready"]);
    expect(summary.buckets.blocked.map((task) => task.id)).toEqual(["feat-blocked"]);
    expect(summary.last_activity_at).toBe("2026-03-19T12:01:00.000Z");

    const workers = await requestJson<{
      project_id: string;
      by_human: Array<{ assignee_human_id: string; tasks: Array<{ id: string }> }>;
      by_agent: Array<{ assignee_agent_id: string; tasks: Array<{ id: string }> }>;
    }>("/projects/proj-core/workers");
    expect(workers.project_id).toBe("proj-core");
    expect(workers.by_human.map((group) => ({
      assignee_human_id: group.assignee_human_id,
      taskIds: group.tasks.map((task) => task.id),
    }))).toEqual([
      { assignee_human_id: "avery", taskIds: ["feat-blocked"] },
      { assignee_human_id: "chad", taskIds: ["feat-ready"] },
    ]);
    expect(workers.by_agent.map((group) => ({
      assignee_agent_id: group.assignee_agent_id,
      taskIds: group.tasks.map((task) => task.id),
    }))).toEqual([
      { assignee_agent_id: "agent-1", taskIds: ["feat-ready"] },
      { assignee_agent_id: "agent-2", taskIds: ["feat-blocked"] },
    ]);

    const brief = await requestJson<{
      snapshot: { total_tasks: number; counts_by_status: Record<string, number> };
      recent_movement: Array<{ task_id: string; from_status: string; to_status: string }>;
      blocked: Array<{ id: string }>;
      ready_for_review: Array<{ id: string }>;
      by_worker: Array<{ worker_id: string; tasks: Array<{ id: string }>; artifact_count: number }>;
      lead_attention_items: Array<{ kind: string; task: { id: string } }>;
      rendered_text: string;
    }>("/projects/proj-core/brief");
    expect(brief.snapshot.total_tasks).toBe(2);
    expect(brief.snapshot.counts_by_status.ready_for_review).toBe(1);
    expect(brief.snapshot.counts_by_status.blocked).toBe(1);
    expect(brief.recent_movement.map((item) => item.task_id)).toEqual(["feat-blocked", "feat-ready"]);
    expect(brief.recent_movement[0]).toEqual(
      expect.objectContaining({
        from_status: "not_started",
        to_status: "blocked",
      }),
    );
    expect(brief.blocked.map((task) => task.id)).toEqual(["feat-blocked"]);
    expect(brief.ready_for_review.map((task) => task.id)).toEqual(["feat-ready"]);
    expect(brief.by_worker.map((group) => ({
      worker_id: group.worker_id,
      taskIds: group.tasks.map((task) => task.id),
      artifact_count: group.artifact_count,
    })).sort((a, b) => a.worker_id.localeCompare(b.worker_id))).toEqual([
      { worker_id: "worker-1", taskIds: ["feat-ready"], artifact_count: 1 },
      { worker_id: "worker-2", taskIds: ["feat-blocked"], artifact_count: 1 },
    ]);
    expect(brief.lead_attention_items.map((item) => ({
      kind: item.kind,
      taskId: item.task.id,
    }))).toEqual([
      { kind: "blocked", taskId: "feat-blocked" },
      { kind: "ready_for_review", taskId: "feat-ready" },
    ]);
    expect(brief.rendered_text).toContain("Project Brief: Core Project (proj-core)");
    expect(brief.rendered_text).toContain("By worker:");
  });

  it("returns structured errors for invalid requests, missing tasks, and duplicates", async () => {
    const invalidCreate = await request("/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id: "bad-task" }),
    });
    expect(invalidCreate.status).toBe(400);
    expect(await invalidCreate.json()).toEqual({
      error: expect.stringContaining("must have required property"),
    });

    const missingTask = await request("/tasks/does-not-exist");
    expect(missingTask.status).toBe(404);
    expect(await missingTask.json()).toEqual({ error: "Task not found: does-not-exist" });

    await request("/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "feat-http",
        title: "HTTP Feature",
        description: "Shared coordination flow",
        assignee_human_id: "chad",
        status: "not_started",
        acceptance_criteria: "Passing test evidence exists",
        acceptance_signals: [
          { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        ],
        depends_on: [],
      }),
    });

    const duplicate = await request("/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "feat-http",
        title: "HTTP Feature",
        description: "Shared coordination flow",
        assignee_human_id: "chad",
        status: "not_started",
        acceptance_criteria: "Passing test evidence exists",
        acceptance_signals: [
          { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        ],
        depends_on: [],
      }),
    });
    expect(duplicate.status).toBe(409);
    expect(await duplicate.json()).toEqual({ error: "Task already exists: feat-http" });

    const missingAssignment = await request("/tasks/does-not-exist/assignments", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ assignee_human_id: "chad" }),
    });
    expect(missingAssignment.status).toBe(404);
    expect(await missingAssignment.json()).toEqual({ error: "Task not found: does-not-exist" });

    const missingIngest = await request("/artifacts/ingest", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        artifact: {
          id: "ra-test-1",
          type: "test_result",
          timestamp: "2026-03-19T12:00:00.000Z",
          source: "worker-connector",
          pointer: "memory://test-run",
          summary: "Passing test evidence",
          raw_payload: {
            type: "test_result",
            signal_id: "sig-test",
            passed: true,
          },
        },
        context: {
          primary_task_id: "does-not-exist",
          session_id: "session-1",
          worker_id: "worker-1",
          context_source: "explicit_lock",
        },
      }),
    });
    expect(missingIngest.status).toBe(404);
    expect(await missingIngest.json()).toEqual({ error: "Task not found: does-not-exist" });

    const missingProject = await request("/projects/does-not-exist");
    expect(missingProject.status).toBe(404);
    expect(await missingProject.json()).toEqual({ error: "Project not found: does-not-exist" });

    await bootstrapOrgFixture();
    await addTeamMemberFixture("chad", "lead", { displayName: "Chad" });

    await request("/projects", {
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
    await request("/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "proj-other",
        title: "Other Project",
        description: "Another project",
        team_id: "team-core",
        owner_worker_id: "chad",
      }),
    });
    const duplicateProject = await request("/projects", {
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
    expect(duplicateProject.status).toBe(409);
    expect(await duplicateProject.json()).toEqual({ error: "Project already exists: proj-core" });
    await request("/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "feat-project",
        title: "Project Task",
        description: "Shared coordination flow",
        assignee_human_id: "chad",
        status: "not_started",
        acceptance_criteria: "Passing test evidence exists",
        acceptance_signals: [
          { id: "sig-project", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        ],
        depends_on: [],
      }),
    });

    const invalidProjectLink = await request("/projects/proj-core/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
    });
    expect(invalidProjectLink.status).toBe(400);
    expect(await invalidProjectLink.json()).toEqual({
      error: expect.stringContaining("must have required property"),
    });

    const unknownProjectLink = await request("/projects/does-not-exist/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_id: "feat-project" }),
    });
    expect(unknownProjectLink.status).toBe(404);
    expect(await unknownProjectLink.json()).toEqual({ error: "Project not found: does-not-exist" });

    const unknownTaskLink = await request("/projects/proj-core/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_id: "does-not-exist" }),
    });
    expect(unknownTaskLink.status).toBe(404);
    expect(await unknownTaskLink.json()).toEqual({ error: "Task not found: does-not-exist" });

    await request("/projects/proj-core/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_id: "feat-project" }),
    });
    const conflictingProjectLink = await request("/projects/proj-other/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_id: "feat-project" }),
    });
    expect(conflictingProjectLink.status).toBe(409);
    expect(await conflictingProjectLink.json()).toEqual({
      error: "Task already linked to different project: feat-project -> proj-core",
    });
  });
});
