// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createEngine } from "../../engine.js";
import { createProgram } from "../../cli/cli.js";
import { getSession, setSession, clearSession, resolveTaskId } from "../../cli/helpers/session.js";
import type { TaskCreate } from "../../types.js";

let dataDir: string;

function makeTask(id = "feat-widget"): TaskCreate {
  return {
    id,
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

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-session-"));
  const engine = createEngine({ dataDir });
  engine.createTask(makeTask());
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
});

describe("session helpers", () => {
  it("returns undefined when no session exists", () => {
    expect(getSession(dataDir)).toBeUndefined();
  });

  it("sets and gets a session", () => {
    setSession(dataDir, "feat-widget");
    const session = getSession(dataDir);
    expect(session?.current_task_id).toBe("feat-widget");
    expect(session?.set_at).toBeTruthy();
  });

  it("rejects setting a nonexistent task", () => {
    expect(() => setSession(dataDir, "nonexistent")).toThrow("Task not found: nonexistent");
  });

  it("clears a session", () => {
    setSession(dataDir, "feat-widget");
    clearSession(dataDir);
    expect(getSession(dataDir)).toBeUndefined();
  });

  it("clearing a nonexistent session is a no-op", () => {
    expect(() => clearSession(dataDir)).not.toThrow();
  });
});

describe("resolveTaskId", () => {
  it("returns explicit --task flag first", () => {
    setSession(dataDir, "feat-widget");
    expect(resolveTaskId({ task: "other-task", dataDir })).toBe("other-task");
  });

  it("falls back to session when no --task flag", () => {
    setSession(dataDir, "feat-widget");
    expect(resolveTaskId({ dataDir })).toBe("feat-widget");
  });

  it("throws with helpful message when no task and no session", () => {
    expect(() => resolveTaskId({ dataDir })).toThrow("No task specified");
    expect(() => resolveTaskId({ dataDir })).toThrow("artifact-loop task use");
  });
});

describe("task use command", () => {
  it("sets the current task and shows confirmation", () => {
    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "use", "feat-widget", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    expect(logs.join("\n")).toContain("Now using task: feat-widget");

    const session = getSession(dataDir);
    expect(session?.current_task_id).toBe("feat-widget");
  });

  it("shows current task when called with no arg", () => {
    setSession(dataDir, "feat-widget");

    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "use", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    expect(logs.join("\n")).toContain("Current task: feat-widget");
  });

  it("shows 'No current task' when no session", () => {
    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "use", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    expect(logs.join("\n")).toContain("No current task");
  });

  it("rejects nonexistent task", () => {
    const errors: string[] = [];
    vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => errors.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "use", "nonexistent", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    expect(errors.join("\n")).toContain("Task not found: nonexistent");
    expect(process.exitCode).toBe(1);
    process.exitCode = undefined;
  });
});

describe("task unuse command", () => {
  it("clears the current task session", () => {
    setSession(dataDir, "feat-widget");

    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "task", "unuse", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    expect(logs.join("\n")).toContain("Cleared current task");
    expect(getSession(dataDir)).toBeUndefined();
  });
});
