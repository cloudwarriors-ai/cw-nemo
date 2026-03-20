// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E Session Workflow: friction-reduced flow using `task use`.
 *
 * Proves that setting a session task removes per-command --task / positional
 * requirements, and that clearing the session restores the error behavior.
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
    id: "feat-widget",
    title: "Widget Feature",
    description: "Build the widget",
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

function runError(args: string[]): string {
  const errors: string[] = [];
  vi.spyOn(console, "error").mockImplementation((...a: unknown[]) => errors.push(String(a[0])));
  const program = createProgram();
  program.parse(["node", "test", ...args]);
  vi.restoreAllMocks();
  return errors.join("\n");
}

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-session-e2e-"));
  const engine = createEngine({ dataDir });
  engine.createTask(makeTask());
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
  process.exitCode = undefined;
});

describe("session workflow: task use → emit without --task → unuse", () => {
  it("completes full friction-reduced lifecycle", () => {
    const d = dataDir;

    // 1. Set working task
    let out = run(["task", "use", "feat-widget", "--data-dir", d]);
    expect(out).toContain("Now using task: feat-widget");

    // 2. Show current task (no arg)
    out = run(["task", "use", "--data-dir", d]);
    expect(out).toContain("Current task: feat-widget");

    // 3. Task status without positional arg → not_started
    out = run(["task", "status", "--data-dir", d]);
    expect(out).toContain("Task: feat-widget (from session)");
    expect(out).toContain("Status: not_started");

    // 4. Emit test pass without --task → ready_for_review
    out = run(["emit", "test", "--signal-id", "sig-test", "--passed", "--data-dir", d]);
    expect(out).toContain("for feat-widget (from session)");
    expect(out).toContain("ready_for_review");
    expect(out).toContain("transition");

    // 5. Task status (no arg) → ready_for_review
    out = run(["task", "status", "--data-dir", d]);
    expect(out).toContain("Task: feat-widget (from session)");
    expect(out).toContain("Status: ready_for_review");

    // 6. Emit merge without --task → done
    out = run(["emit", "merge", "--signal-id", "sig-merge", "--ref", "abc123", "--branch", "main", "--data-dir", d]);
    expect(out).toContain("for feat-widget (from session)");
    expect(out).toContain("done");
    expect(out).toContain("transition");

    // 7. Task history (no arg) → shows transitions
    out = run(["task", "history", "--data-dir", d]);
    expect(out).toContain("Task: feat-widget (from session)");
    expect(out).toContain("not_started");
    expect(out).toContain("ready_for_review");
    expect(out).toContain("done");

    // 8. Unuse → clear session
    out = run(["task", "unuse", "--data-dir", d]);
    expect(out).toContain("Cleared current task");

    // 9. Task status (no arg) → error with helpful message
    const errorOut = runError(["task", "status", "--data-dir", d]);
    expect(errorOut).toContain("No task specified");
    expect(process.exitCode).toBe(1);
  });
});
