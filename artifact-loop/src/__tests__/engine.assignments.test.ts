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

function makeTask(): TaskCreate {
  return {
    id: "feat-http",
    title: "HTTP Feature",
    description: "Shared coordination test task",
    assignee_human_id: "chad",
    status: "not_started",
    acceptance_criteria: "Passing test evidence exists",
    acceptance_signals: [
      { id: "sig-test", category: "test", required: true, success_condition: "tests pass" },
    ],
    depends_on: [],
  };
}

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-engine-assign-"));
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
});

describe("engine assignments and provenance", () => {
  it("creates append-only assignments and updates current task assignees", async () => {
    const engine = createEngine({ dataDir });
    engine.createWorker({ id: "chad", display_name: "Chad", role: "lead", timezone: "America/New_York" });
    engine.createWorker({ id: "avery", display_name: "Avery", role: "worker", timezone: "America/New_York" });
    engine.createWorker({ id: "lead", display_name: "Lead", role: "lead", timezone: "America/New_York" });
    engine.createWorker({ id: "lead-2", display_name: "Lead Two", role: "lead", timezone: "America/New_York" });
    engine.createWorkerAgent("chad", {
      id: "worker-agent-1",
      label: "Worker Agent 1",
      connector_type: "remote",
    });
    engine.createTask(makeTask());

    const first = engine.createAssignment("feat-http", {
      assignee_human_id: "chad",
      assignee_agent_id: "worker-agent-1",
      assigned_by: "lead",
    });
    const second = engine.createAssignment("feat-http", {
      assignee_human_id: "avery",
      assigned_by: "lead-2",
    });

    const assignments = engine.getAssignments("feat-http");
    expect(assignments).toHaveLength(2);
    expect(assignments[0]?.id).toBe(first.id);
    expect(assignments[1]?.id).toBe(second.id);
    expect(assignments[0]?.assignee_agent_id).toBe("worker-agent-1");
    expect(assignments[1]?.assignee_agent_id).toBeUndefined();

    const task = engine.getTask("feat-http");
    expect(task?.assignee_human_id).toBe("avery");
    expect(task?.assignee_agent_id).toBeUndefined();
  });

  it("persists worker provenance on normalized artifacts without changing derivation semantics", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask());

    const payload: TestResultPayload = {
      type: "test_result",
      signal_id: "sig-test",
      passed: true,
    };

    const result = engine.ingest(
      buildRawArtifact("test_result", payload, "Passing test"),
      {
        primary_task_id: "feat-http",
        session_id: "session-1",
        worker_id: "worker-1",
        worker_agent_id: "worker-agent-1",
        context_source: "explicit_lock",
      },
    );

    expect(result.normalizedArtifact.worker_id).toBe("worker-1");
    expect(result.normalizedArtifact.worker_agent_id).toBe("worker-agent-1");
    expect(result.normalizedArtifact.context_source).toBe("explicit_lock");
    expect(result.normalizedArtifact.artifact_source).toBe("cli");
    expect(engine.getTaskState("feat-http")?.status).toBe("ready_for_review");
  });
});
