// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createEngine } from "../../engine.js";
import { createProgram } from "../../cli/cli.js";
import { buildContext } from "../../cli/helpers/context.js";
import { buildRawArtifact } from "../../cli/helpers/raw-artifact.js";
import { setSession } from "../../cli/helpers/session.js";
import type { FileChangePayload, TaskCreate } from "../../types.js";

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
  process.exitCode = undefined;
});

function run(args: string[]): string {
  const logs: string[] = [];
  vi.spyOn(console, "log").mockImplementation((...a: unknown[]) => logs.push(String(a[0])));
  const program = createProgram();
  program.parse(["node", "test", ...args]);
  vi.restoreAllMocks();
  return logs.join("\n");
}

describe("task status", () => {
  it("shows task status in human format", () => {
    const output = run(["task", "status", "test-task", "--data-dir", dataDir]);
    expect(output).toContain("Task: test-task");
    expect(output).not.toContain("(from session)");
    expect(output).toContain("Status: not_started");
    expect(output).toContain("Confidence: 0%");
    expect(output).toContain("Signals:");
    expect(output).toContain("[sig-test] (test, required) not yet satisfied");
    expect(output).toContain("Next likely step:");
    expect(output).toContain("artifact-loop run --signal-id sig-test -- <command>");
  });

  it("shows task status in JSON format", () => {
    const parsed = JSON.parse(run(["task", "status", "test-task", "--json", "--data-dir", dataDir]));
    expect(parsed.task.id).toBe("test-task");
    expect(parsed.state.status).toBe("not_started");
    expect(parsed.signalStatuses).toBeUndefined();
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
    const output = run(["task", "status", "--data-dir", dataDir]);
    expect(output).toContain("Task: test-task (from session)");
    expect(output).toContain("Status: not_started");
    expect(output).toContain("[sig-test] (test, required) not yet satisfied");
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

describe("task status signal visibility", () => {
  it("shows satisfied test signals and removes next-step hint when all required signals are satisfied", () => {
    run(["emit", "test", "--task", "test-task", "--signal-id", "sig-test", "--passed", "--data-dir", dataDir]);

    const output = run(["task", "status", "test-task", "--data-dir", dataDir]);
    expect(output).toContain("Status: ready_for_review");
    expect(output).toContain("[sig-test] (test, required) satisfied");
    expect(output).not.toContain("Next likely step:");
  });

  it("shows failed required test signals and keeps the rerun hint", () => {
    run(["emit", "test", "--task", "test-task", "--signal-id", "sig-test", "--failed", "--data-dir", dataDir]);

    const output = run(["task", "status", "test-task", "--data-dir", dataDir]);
    expect(output).toContain("Status: blocked");
    expect(output).toContain("[sig-test] (test, required) failed");
    expect(output).toContain("artifact-loop run --signal-id sig-test -- <command>");
  });

  it("shows command signal status from command_result evidence", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask({
      id: "command-task",
      acceptance_signals: [
        { id: "sig-command", category: "command", required: true, success_condition: "exit code 0", command: "node -e" },
      ],
    }));

    run([
      "run",
      "--task", "command-task",
      "--signal-id", "sig-command",
      "--kind", "command",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('ok')",
    ]);

    const output = run(["task", "status", "command-task", "--data-dir", dataDir]);
    expect(output).toContain("[sig-command] (command, required) satisfied");
    expect(output).not.toContain("Next likely step:");
  });

  it("shows merge signal progress and advances the next-step hint", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask({
      id: "merge-task",
      acceptance_criteria: "tests pass and merged",
      acceptance_signals: [
        { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        { id: "sig-merge", category: "merge", required: true, success_condition: "merged to main" },
      ],
    }));

    let output = run(["task", "status", "merge-task", "--data-dir", dataDir]);
    expect(output).toContain("[sig-test] (test, required) not yet satisfied");
    expect(output).toContain("[sig-merge] (merge, required) not yet satisfied");
    expect(output).toContain("artifact-loop run --signal-id sig-test -- <command>");

    run(["emit", "test", "--task", "merge-task", "--signal-id", "sig-test", "--passed", "--data-dir", dataDir]);
    output = run(["task", "status", "merge-task", "--data-dir", dataDir]);
    expect(output).toContain("[sig-test] (test, required) satisfied");
    expect(output).toContain("[sig-merge] (merge, required) not yet satisfied");
    expect(output).toContain("artifact-loop emit merge --signal-id sig-merge --ref <ref> --branch <branch>");

    run(["emit", "merge", "--task", "merge-task", "--signal-id", "sig-merge", "--ref", "abc123", "--branch", "main", "--data-dir", dataDir]);
    output = run(["task", "status", "merge-task", "--data-dir", dataDir]);
    expect(output).toContain("[sig-merge] (merge, required) satisfied");
    expect(output).not.toContain("Next likely step:");
  });

  it("shows optional file signals and uses a descriptive file hint", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask({
      id: "file-task",
      acceptance_signals: [
        { id: "sig-file", category: "file", required: true, success_condition: "file exists", path: "src/index.ts" },
        { id: "sig-merge", category: "merge", required: false, success_condition: "merged to main" },
      ],
    }));

    let output = run(["task", "status", "file-task", "--data-dir", dataDir]);
    expect(output).toContain("[sig-file] (file, required) not yet satisfied");
    expect(output).toContain("[sig-merge] (merge, optional) not yet satisfied");
    expect(output).toContain("Produce file evidence for src/index.ts");

    const payload: FileChangePayload = {
      type: "file_change",
      signal_id: "sig-file",
      path: "src/index.ts",
      change_type: "modified",
    };
    engine.ingest(
      buildRawArtifact("file_change", payload, "File changed"),
      buildContext({ task: "file-task" }),
    );

    output = run(["task", "status", "file-task", "--data-dir", dataDir]);
    expect(output).toContain("[sig-file] (file, required) satisfied");
    expect(output).not.toContain("Next likely step:");
  });
});

describe("task history", () => {
  it("shows empty history for new task", () => {
    const output = run(["task", "history", "test-task", "--data-dir", dataDir]);
    expect(output).toContain("Task: test-task");
    expect(output).toContain("No derivation history");
    expect(output).not.toContain("(from session)");
  });

  it("uses session task when no positional arg", () => {
    setSession(dataDir, "test-task");
    const output = run(["task", "history", "--data-dir", dataDir]);
    expect(output).toContain("Task: test-task (from session)");
    expect(output).toContain("No derivation history");
  });
});
