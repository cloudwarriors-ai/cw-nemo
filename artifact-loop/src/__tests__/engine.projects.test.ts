// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createEngine } from "../engine.js";
import { buildRawArtifact } from "../cli/helpers/raw-artifact.js";
import type { TaskCreate, TestResultPayload } from "../types.js";

let dataDir: string;

function bootstrapOrg(engine: ReturnType<typeof createEngine>): void {
  engine.bootstrapOrganization({
    organization: {
      id: "org-core",
      name: "Core Org",
      timezone: "America/New_York",
    },
    initial_team: {
      id: "team-core",
      name: "Core Team",
      description: "Projects test team",
    },
    initial_member: {
      id: "lead-1",
      display_name: "Lead",
      timezone: "America/New_York",
    },
    initial_agent: {
      id: "lead-agent-1",
      label: "Lead Agent",
      connector_type: "lead-cli",
    },
  });
}

function makeTask(id: string, overrides: Partial<TaskCreate> = {}): TaskCreate {
  return {
    id,
    title: id,
    description: `${id} task`,
    assignee_human_id: "chad",
    status: "not_started",
    acceptance_criteria: "tests pass",
    acceptance_signals: [
      { id: `${id}-sig-test`, category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
    ],
    depends_on: [],
    ...overrides,
  };
}

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-engine-projects-"));
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
});

describe("engine projects", () => {
  it("creates and lists persisted projects", () => {
    const engine = createEngine({ dataDir });
    bootstrapOrg(engine);
    const project = engine.createProject({
      id: "proj-core",
      team_id: "team-core",
      title: "Core Project",
      description: "Lead-readable coordination surface",
      owner_worker_id: "lead-1",
    });

    expect(engine.getProject("proj-core")).toEqual(project);
    expect(engine.getProjects().map((entry) => entry.id)).toEqual(["proj-core"]);
  });

  it("links tasks to one current project and rejects conflicting project links", () => {
    const engine = createEngine({ dataDir });
    bootstrapOrg(engine);
    engine.createProject({ id: "proj-core", team_id: "team-core", title: "Core Project", description: "Core", owner_worker_id: "lead-1" });
    engine.createProject({ id: "proj-other", team_id: "team-core", title: "Other Project", description: "Other", owner_worker_id: "lead-1" });
    engine.createTask(makeTask("feat-http"));

    const linked = engine.assignTaskToProject("proj-core", "feat-http");
    expect(linked.project_id).toBe("proj-core");
    expect(engine.getTask("feat-http")?.project_id).toBe("proj-core");

    const sameAgain = engine.assignTaskToProject("proj-core", "feat-http");
    expect(sameAgain.project_id).toBe("proj-core");

    expect(() => engine.assignTaskToProject("proj-other", "feat-http")).toThrow(
      "Task already linked to different project: feat-http -> proj-core",
    );
  });

  it("computes project summary from current task states and groups workers by human and agent", () => {
    const engine = createEngine({ dataDir });
    bootstrapOrg(engine);
    engine.createProject({
      id: "proj-core",
      team_id: "team-core",
      title: "Core Project",
      description: "Lead-readable coordination surface",
      owner_worker_id: "lead-1",
    });
    engine.createTask(makeTask("feat-ready", {
      assignee_agent_id: "agent-1",
    }));
    engine.createTask(makeTask("feat-blocked", {
      assignee_human_id: "avery",
      assignee_agent_id: "agent-2",
    }));

    engine.assignTaskToProject("proj-core", "feat-ready");
    engine.assignTaskToProject("proj-core", "feat-blocked");

    const readyPayload: TestResultPayload = {
      type: "test_result",
      signal_id: "feat-ready-sig-test",
      passed: true,
    };
    engine.ingest(
      buildRawArtifact("test_result", readyPayload, "Passing test"),
      {
        primary_task_id: "feat-ready",
        session_id: "session-1",
        worker_id: "worker-1",
        context_source: "explicit_lock",
      },
    );

    const blockedPayload: TestResultPayload = {
      type: "test_result",
      signal_id: "feat-blocked-sig-test",
      passed: false,
    };
    engine.ingest(
      buildRawArtifact("test_result", blockedPayload, "Failing test"),
      {
        primary_task_id: "feat-blocked",
        session_id: "session-1",
        worker_id: "worker-2",
        context_source: "explicit_lock",
      },
    );

    const summary = engine.getProjectSummary("proj-core");
    expect(summary.total_tasks).toBe(2);
    expect(summary.counts_by_status.ready_for_review).toBe(1);
    expect(summary.counts_by_status.blocked).toBe(1);
    expect(summary.buckets.ready_for_review.map((task) => task.id)).toEqual(["feat-ready"]);
    expect(summary.buckets.blocked.map((task) => task.id)).toEqual(["feat-blocked"]);
    expect(summary.last_activity_at).toBeTruthy();

    const workerSummary = engine.getProjectWorkerSummary("proj-core");
    expect(workerSummary.by_human).toEqual([
      {
        assignee_human_id: "avery",
        tasks: [expect.objectContaining({ id: "feat-blocked", status: "blocked" })],
      },
      {
        assignee_human_id: "chad",
        tasks: [expect.objectContaining({ id: "feat-ready", status: "ready_for_review" })],
      },
    ]);
    expect(workerSummary.by_agent).toEqual([
      {
        assignee_agent_id: "agent-1",
        tasks: [expect.objectContaining({ id: "feat-ready", status: "ready_for_review" })],
      },
      {
        assignee_agent_id: "agent-2",
        tasks: [expect.objectContaining({ id: "feat-blocked", status: "blocked" })],
      },
    ]);
  });

  it("builds a grounded project brief from summary buckets and recent derivation movement", () => {
    const engine = createEngine({ dataDir });
    bootstrapOrg(engine);
    engine.createProject({
      id: "proj-core",
      team_id: "team-core",
      title: "Core Project",
      description: "Lead-readable coordination surface",
      owner_worker_id: "lead-1",
    });
    engine.createTask(makeTask("feat-review", {
      assignee_agent_id: "agent-1",
      acceptance_signals: [
        { id: "feat-review-sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
      ],
    }));
    engine.createTask(makeTask("feat-blocked", {
      assignee_human_id: "avery",
      assignee_agent_id: "agent-2",
    }));
    engine.assignTaskToProject("proj-core", "feat-review");
    engine.assignTaskToProject("proj-core", "feat-blocked");

    engine.ingest(
      buildRawArtifact("test_result", {
        type: "test_result",
        signal_id: "feat-review-sig-test",
        passed: true,
      }, "Passing test"),
      {
        primary_task_id: "feat-review",
        session_id: "session-1",
        worker_id: "worker-1",
        context_source: "explicit_lock",
      },
    );
    engine.ingest(
      buildRawArtifact("test_result", {
        type: "test_result",
        signal_id: "feat-blocked-sig-test",
        passed: false,
      }, "Failing test"),
      {
        primary_task_id: "feat-blocked",
        session_id: "session-1",
        worker_id: "worker-2",
        context_source: "explicit_lock",
      },
    );

    const brief = engine.getProjectBrief("proj-core");
    expect(brief.snapshot.total_tasks).toBe(2);
    expect(brief.snapshot.counts_by_status.ready_for_review).toBe(1);
    expect(brief.snapshot.counts_by_status.blocked).toBe(1);
    expect(brief.recent_movement).toHaveLength(2);
    expect(brief.recent_movement[0]?.task_id).toBe("feat-blocked");
    expect(brief.blocked.map((task) => task.id)).toEqual(["feat-blocked"]);
    expect(brief.ready_for_review.map((task) => task.id)).toEqual(["feat-review"]);
    expect(brief.by_worker.map((group) => ({
      worker_id: group.worker_id,
      taskIds: group.tasks.map((task) => task.id),
      artifact_count: group.artifact_count,
    })).sort((a, b) => a.worker_id.localeCompare(b.worker_id))).toEqual([
      {
        worker_id: "worker-1",
        taskIds: ["feat-review"],
        artifact_count: 1,
      },
      {
        worker_id: "worker-2",
        taskIds: ["feat-blocked"],
        artifact_count: 1,
      },
    ]);
    expect(brief.lead_attention_items.map((item) => item.kind)).toEqual([
      "blocked",
      "ready_for_review",
    ]);
    expect(brief.rendered_text).toContain("Project Brief: Core Project (proj-core)");
    expect(brief.rendered_text).toContain("By worker:");
    expect(brief.rendered_text).toContain("worker-1");
    expect(brief.rendered_text).toContain("Recent movement:");
    expect(brief.rendered_text).toContain("Lead attention:");
  });
});
