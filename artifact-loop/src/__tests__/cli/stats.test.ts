// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createEngine } from "../../engine.js";
import { createProgram } from "../../cli/cli.js";
import type { TaskCreate } from "../../types.js";

let dataDir: string;

function makeTask(id: string): TaskCreate {
  return {
    id,
    title: id,
    description: id,
    assignee_human_id: "chad",
    status: "not_started",
    acceptance_criteria: "tests pass",
    acceptance_signals: [
      { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
    ],
    depends_on: [],
  };
}

function runCli(args: string[]): string {
  const logs: string[] = [];
  vi.spyOn(console, "log").mockImplementation((...a: unknown[]) => logs.push(String(a[0])));
  const program = createProgram();
  program.parse(["node", "test", ...args]);
  vi.restoreAllMocks();
  return logs.join("\n");
}

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-stats-"));
  const engine = createEngine({ dataDir });
  engine.createTask(makeTask("feat-auto"));
  engine.createTask(makeTask("feat-manual"));
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
  process.exitCode = undefined;
});

describe("stats", () => {
  it("reports raw counts for usage, artifacts, overrides, and evidence buckets", () => {
    runCli(["task", "use", "feat-auto", "--data-dir", dataDir]);
    runCli(["emit", "test", "--signal-id", "sig-test", "--passed", "--data-dir", dataDir]);
    runCli(["task", "use", "feat-manual", "--data-dir", dataDir]);
    runCli([
      "emit", "note",
      "--event-type", "context_note",
      "--description", "manual only",
      "--by", "chad",
      "--data-dir", dataDir,
    ]);
    runCli(["task", "status", "feat-auto", "--data-dir", dataDir]);
    const engine = createEngine({ dataDir });
    engine.applyOverride("feat-auto", {
      status: "ready_for_review",
      reason: "manual override",
      by: "chad",
      timestamp: new Date().toISOString(),
    });
    runCli(["task", "unuse", "--data-dir", dataDir]);

    const stats = JSON.parse(runCli(["stats", "--json", "--data-dir", dataDir]));

    expect(stats.task_use).toEqual({ set: 1, change: 1, clear: 1 });
    expect(stats.command_resolution.session_default).toBe(2);
    expect(stats.command_resolution.explicit_lock).toBe(1);
    expect(stats.command_resolution.explicit_over_session_override).toBe(1);
    expect(stats.artifacts_by_type.test_result).toBe(1);
    expect(stats.artifacts_by_type.manual_event).toBe(1);
    expect(stats.override_by_resulting_status.ready_for_review).toBe(1);
    expect(stats.evidence_buckets).toEqual({
      automatic_any: 1,
      manual_only: 1,
      merge_only: 0,
      none: 0,
    });
  });
});
