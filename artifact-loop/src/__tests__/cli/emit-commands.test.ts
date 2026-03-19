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

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-emit-"));
  const engine = createEngine({ dataDir });
  engine.createTask(makeTask());
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
});

describe("emit test", () => {
  it("emits a passing test result and triggers derivation", () => {
    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "emit", "test", "--task", "feat-widget", "--signal-id", "sig-test", "--passed", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    const output = logs.join("\n");
    expect(output).toContain("passed");
    expect(output).toContain("for feat-widget");
    expect(output).not.toContain("(from session)");
    expect(output).toContain("ready_for_review");
    expect(output).toContain("transition");

    // Verify state persisted
    const engine = createEngine({ dataDir });
    const state = engine.getTaskState("feat-widget");
    expect(state?.status).toBe("ready_for_review");
  });

  it("emits a failing test result and blocks task", () => {
    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "emit", "test", "--task", "feat-widget", "--signal-id", "sig-test", "--failed", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    const output = logs.join("\n");
    expect(output).toContain("failed");
    expect(output).toContain("for feat-widget");
    expect(output).toContain("blocked");

    const engine = createEngine({ dataDir });
    const state = engine.getTaskState("feat-widget");
    expect(state?.status).toBe("blocked");
  });

  it("rejects when neither --passed nor --failed", () => {
    const errors: string[] = [];
    vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => errors.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "emit", "test", "--task", "feat-widget", "--signal-id", "sig-test", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    expect(errors.join("\n")).toContain("Must specify --passed or --failed");
    expect(process.exitCode).toBe(1);
    process.exitCode = undefined;
  });
});

describe("emit note", () => {
  it("emits a context note", () => {
    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse([
      "node", "test", "emit", "note",
      "--task", "feat-widget",
      "--event-type", "context_note",
      "--description", "Widget looks good in Safari",
      "--by", "chad",
      "--data-dir", dataDir,
    ]);

    vi.restoreAllMocks();

    const output = logs.join("\n");
    expect(output).toContain("context_note");
    expect(output).toContain("for feat-widget");

    // Verify artifact persisted
    const engine = createEngine({ dataDir });
    const artifacts = engine.getArtifacts("feat-widget");
    expect(artifacts.length).toBe(1);
    expect(artifacts[0].signal_payload.type).toBe("manual_event");
  });

  it("rejects invalid event type", () => {
    const errors: string[] = [];
    vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => errors.push(String(args[0])));

    const program = createProgram();
    program.parse([
      "node", "test", "emit", "note",
      "--task", "feat-widget",
      "--event-type", "invalid_type",
      "--description", "test",
      "--by", "chad",
      "--data-dir", dataDir,
    ]);

    vi.restoreAllMocks();

    expect(errors.join("\n")).toContain("Invalid event type");
    expect(process.exitCode).toBe(1);
    process.exitCode = undefined;
  });
});

describe("emit with session default", () => {
  it("emits test result using session task when --task omitted", () => {
    setSession(dataDir, "feat-widget");

    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "emit", "test", "--signal-id", "sig-test", "--passed", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    const output = logs.join("\n");
    expect(output).toContain("passed");
    expect(output).toContain("for feat-widget (from session)");
    expect(output).toContain("ready_for_review");

    const engine = createEngine({ dataDir });
    const state = engine.getTaskState("feat-widget");
    expect(state?.status).toBe("ready_for_review");
  });

  it("explicit --task overrides session", () => {
    // Create a second task
    const engine = createEngine({ dataDir });
    engine.createTask({
      id: "other-task",
      title: "Other Task",
      description: "Another task",
      assignee_human_id: "chad",
      status: "not_started",
      acceptance_criteria: "tests pass",
      acceptance_signals: [
        { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
      ],
      depends_on: [],
    });

    setSession(dataDir, "feat-widget");

    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program = createProgram();
    program.parse(["node", "test", "emit", "test", "--task", "other-task", "--signal-id", "sig-test", "--passed", "--data-dir", dataDir]);

    vi.restoreAllMocks();

    // other-task should have transitioned, not feat-widget
    expect(logs.join("\n")).toContain("for other-task");
    expect(logs.join("\n")).not.toContain("(from session)");
    const otherState = engine.getTaskState("other-task");
    expect(otherState?.status).toBe("ready_for_review");

    const widgetState = engine.getTaskState("feat-widget");
    expect(widgetState?.status).toBe("not_started");
  });
});

describe("emit merge", () => {
  it("emits a merge result", () => {
    // First pass the test to get to ready_for_review
    const program1 = createProgram();
    vi.spyOn(console, "log").mockImplementation(() => {});
    program1.parse(["node", "test", "emit", "test", "--task", "feat-widget", "--signal-id", "sig-test", "--passed", "--data-dir", dataDir]);
    vi.restoreAllMocks();

    // Now emit merge
    const logs: string[] = [];
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => logs.push(String(args[0])));

    const program2 = createProgram();
    program2.parse([
      "node", "test", "emit", "merge",
      "--task", "feat-widget",
      "--signal-id", "sig-merge",
      "--ref", "abc123",
      "--branch", "main",
      "--data-dir", dataDir,
    ]);

    vi.restoreAllMocks();

    const output = logs.join("\n");
    expect(output).toContain("merge_result");
    expect(output).toContain("for feat-widget");
    expect(output).toContain("done");
    expect(output).toContain("transition");

    const engine = createEngine({ dataDir });
    const state = engine.getTaskState("feat-widget");
    expect(state?.status).toBe("done");
  });
});
