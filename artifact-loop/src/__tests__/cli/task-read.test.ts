// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createEngine } from "../../engine.js";
import { createProgram } from "../../cli/cli.js";
import { setSession } from "../../cli/helpers/session.js";
import type { TaskCreate } from "../../types.js";

let dataDir: string;

function makeTask(overrides?: Partial<TaskCreate>): TaskCreate {
  return {
    id: "test-task",
    title: "Test Task",
    description: "A test task",
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

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-test-"));
  const engine = createEngine({ dataDir });
  engine.createTask(makeTask());
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
});

describe("task status", () => {
  it("shows task status in human format", () => {
    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "status", "test-task", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    const output = logs.join("\n");
    expect(output).toContain("Task: test-task");
    expect(output).not.toContain("(from session)");
    expect(output).toContain("Status: not_started");
    expect(output).toContain("Confidence: 0%");
  });

  it("shows task status in JSON format", () => {
    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "status", "test-task", "--json", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    const parsed = JSON.parse(logs.join("\n"));
    expect(parsed.task.id).toBe("test-task");
    expect(parsed.state.status).toBe("not_started");
  });

  it("reports error for unknown task", () => {
    const errors: string[] = [];
    vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => errors.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "status", "nonexistent", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    expect(errors.join("\n")).toContain("Task not found");
    expect(process.exitCode).toBe(1);
    process.exitCode = undefined;
  });
});

describe("task status with session default", () => {
  it("uses session task when no positional arg", () => {
    setSession(dataDir, "test-task");

    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "status", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    const output = logs.join("\n");
    expect(output).toContain("Task: test-task (from session)");
    expect(output).toContain("Status: not_started");
  });

  it("errors with helpful message when no arg and no session", () => {
    const errors: string[] = [];
    vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => errors.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "status", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    expect(errors.join("\n")).toContain("No task specified");
    expect(process.exitCode).toBe(1);
    process.exitCode = undefined;
  });
});

describe("task history", () => {
  it("shows empty history for new task", () => {
    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "history", "test-task", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    const output = logs.join("\n");
    expect(output).toContain("Task: test-task");
    expect(output).toContain("No derivation history");
    expect(output).not.toContain("(from session)");
  });

  it("uses session task when no positional arg", () => {
    setSession(dataDir, "test-task");

    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "history", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    const output = logs.join("\n");
    expect(output).toContain("Task: test-task (from session)");
    expect(output).toContain("No derivation history");
  });
});
