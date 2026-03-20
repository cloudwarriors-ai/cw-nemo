// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E Golden Path: not_started → ready_for_review → done
 *
 * Setup: create task via engine with test + merge signals.
 * Exercise: emit test pass → emit merge → verify done.
 * Verify: task history shows full transition chain.
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

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-golden-"));
  const engine = createEngine({ dataDir });
  engine.createTask(makeTask());
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
});

describe("golden path: not_started → ready_for_review → done", () => {
  it("completes the full lifecycle via CLI emit commands", () => {
    const engine = createEngine({ dataDir });

    // 1. Initial state: not_started
    let statusOut = run(["task", "status", "feat-widget", "--data-dir", dataDir]);
    expect(statusOut).toContain("Task: feat-widget");
    expect(statusOut).not.toContain("(from session)");
    expect(statusOut).toContain("Status: not_started");

    // 2. Emit passing test → ready_for_review
    let emitOut = run(["emit", "test", "--task", "feat-widget", "--signal-id", "sig-test", "--passed", "--data-dir", dataDir]);
    expect(emitOut).toContain("for feat-widget");
    expect(emitOut).not.toContain("(from session)");
    expect(emitOut).toContain("ready_for_review");
    expect(emitOut).toContain("transition");

    statusOut = run(["task", "status", "feat-widget", "--data-dir", dataDir]);
    expect(statusOut).toContain("Status: ready_for_review");

    // 3. Emit merge → done
    emitOut = run(["emit", "merge", "--task", "feat-widget", "--signal-id", "sig-merge", "--ref", "abc123", "--branch", "main", "--data-dir", dataDir]);
    expect(emitOut).toContain("for feat-widget");
    expect(emitOut).not.toContain("(from session)");
    expect(emitOut).toContain("done");
    expect(emitOut).toContain("transition");

    statusOut = run(["task", "status", "feat-widget", "--data-dir", dataDir]);
    expect(statusOut).toContain("Status: done");

    // 4. Verify JSON output shows done with full confidence
    const jsonOut = run(["task", "status", "feat-widget", "--json", "--data-dir", dataDir]);
    const parsed = JSON.parse(jsonOut);
    expect(parsed.state.status).toBe("done");
    expect(parsed.state.task_confidence).toBe(1);

    // 5. Verify derivation history shows both transitions
    const historyOut = run(["task", "history", "feat-widget", "--data-dir", dataDir]);
    expect(historyOut).toContain("Task: feat-widget");
    expect(historyOut).not.toContain("(from session)");
    expect(historyOut).toContain("not_started");
    expect(historyOut).toContain("ready_for_review");
    expect(historyOut).toContain("done");

    // Also check via engine directly
    const history = engine.getDerivationHistory("feat-widget");
    expect(history.length).toBe(2);
    expect(history[0].prior_state).toBe("not_started");
    expect(history[0].output_state).toBe("ready_for_review");
    expect(history[1].prior_state).toBe("ready_for_review");
    expect(history[1].output_state).toBe("done");
  });
});
