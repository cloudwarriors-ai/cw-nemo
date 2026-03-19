// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E Failure / Escape Hatch: ready_for_review → blocked → override → ready_for_review
 *
 * Setup: create task, advance to ready_for_review via test pass.
 * Exercise: emit test failure → blocked, then override via engine → ready_for_review.
 * Verify: history shows override_application rule.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createEngine } from "../../../engine.js";
import { createProgram } from "../../../cli/cli.js";
import type { TaskCreate } from "../../../types.js";

let dataDir: string;

function makeTask(): TaskCreate {
  return {
    id: "feat-escape",
    title: "Escape Hatch Feature",
    description: "Test the failure-recovery path",
    assignee_human_id: "chad",
    status: "not_started",
    acceptance_criteria: "tests pass and merged",
    acceptance_signals: [
      { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
      { id: "sig-merge", category: "merge", required: true, success_condition: "merged to main" },
    ],
    depends_on: [],
  };
}

function run(args: string[]): string {
  const logs: string[] = [];
  vi.spyOn(console, "log").mockImplementation((...a: unknown[]) => logs.push(String(a[0])));
  const program = createProgram();
  program.parse(["node", "test", ...args]);
  vi.restoreAllMocks();
  return logs.join("\n");
}

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-escape-"));
  const engine = createEngine({ dataDir });
  engine.createTask(makeTask());
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
});

describe("failure / escape hatch: blocked → override → recovers", () => {
  it("recovers from blocked state via engine override", () => {
    const engine = createEngine({ dataDir });

    // 1. Advance to ready_for_review via passing test
    run(["emit", "test", "--task", "feat-escape", "--signal-id", "sig-test", "--passed", "--data-dir", dataDir]);
    let state = engine.getTaskState("feat-escape");
    expect(state?.status).toBe("ready_for_review");

    // 2. Emit failing test → blocked (failure dominates)
    let emitOut = run(["emit", "test", "--task", "feat-escape", "--signal-id", "sig-test", "--failed", "--data-dir", dataDir]);
    expect(emitOut).toContain("for feat-escape");
    expect(emitOut).not.toContain("(from session)");
    expect(emitOut).toContain("blocked");

    const statusOut = run(["task", "status", "feat-escape", "--data-dir", dataDir]);
    expect(statusOut).toContain("Status: blocked");

    // 3. Apply override via engine directly (CLI override is Phase 6)
    engine.applyOverride("feat-escape", {
      status: "ready_for_review",
      reason: "Test failure was flaky, overriding",
      by: "chad",
      timestamp: new Date().toISOString(),
    });

    state = engine.getTaskState("feat-escape");
    expect(state?.status).toBe("ready_for_review");

    // 4. Verify via CLI status
    const statusAfter = run(["task", "status", "feat-escape", "--data-dir", dataDir]);
    expect(statusAfter).toContain("Status: ready_for_review");

    // 5. Verify history shows override_application rule
    const historyOut = run(["task", "history", "feat-escape", "--data-dir", dataDir]);
    expect(historyOut).toContain("Task: feat-escape");
    expect(historyOut).not.toContain("(from session)");
    expect(historyOut).toContain("override_application");

    // Also verify via engine
    const history = engine.getDerivationHistory("feat-escape");
    expect(history.length).toBeGreaterThanOrEqual(3);

    // Find the override transition
    const overrideRun = history.find((r) => r.rules_applied.includes("override_application"));
    expect(overrideRun).toBeDefined();
    expect(overrideRun!.prior_state).toBe("blocked");
    expect(overrideRun!.output_state).toBe("ready_for_review");
  });
});
