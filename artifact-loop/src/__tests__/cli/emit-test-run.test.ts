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

function makeTask(): TaskCreate {
  return {
    id: "feat-run",
    title: "Test Run Feature",
    description: "Test the test-run command",
    assignee_human_id: "chad",
    status: "not_started",
    acceptance_criteria: "tests pass",
    acceptance_signals: [
      { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
    ],
    depends_on: [],
  };
}

function run(args: string[]): { stdout: string; stderr: string; logs: string } {
  const stdout: string[] = [];
  const stderr: string[] = [];
  const logs: string[] = [];

  vi.spyOn(process.stdout, "write").mockImplementation(((chunk: string | Uint8Array) => {
    stdout.push(String(chunk));
    return true;
  }) as typeof process.stdout.write);
  vi.spyOn(process.stderr, "write").mockImplementation(((chunk: string | Uint8Array) => {
    stderr.push(String(chunk));
    return true;
  }) as typeof process.stderr.write);
  vi.spyOn(console, "log").mockImplementation((...a: unknown[]) => logs.push(String(a[0])));

  const program = createProgram();
  program.parse(["node", "test", ...args]);

  vi.restoreAllMocks();
  return {
    stdout: stdout.join(""),
    stderr: stderr.join(""),
    logs: logs.join("\n"),
  };
}

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-run-"));
  const engine = createEngine({ dataDir });
  engine.createTask(makeTask());
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
  process.exitCode = undefined;
});

describe("emit test-run", () => {
  it("captures a passing command", () => {
    const result = run([
      "emit", "test-run",
      "--task", "feat-run",
      "--signal-id", "sig-test",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('hello')",
    ]);

    expect(result.stdout).toContain("hello");
    expect(result.logs).toContain("passed");
    expect(result.logs).toContain("for feat-run");
    expect(result.logs).not.toContain("(from session)");
    expect(result.logs).toContain("ready_for_review");

    const engine = createEngine({ dataDir });
    const state = engine.getTaskState("feat-run");
    expect(state?.status).toBe("ready_for_review");
  });

  it("captures a failing command", () => {
    const result = run([
      "emit", "test-run",
      "--task", "feat-run",
      "--signal-id", "sig-test",
      "--data-dir", dataDir,
      "--", "node", "-e", "process.exit(1)",
    ]);

    expect(result.logs).toContain("failed");
    expect(result.logs).toContain("for feat-run");
    expect(result.logs).not.toContain("(from session)");
    expect(result.logs).toContain("blocked");
    expect(process.exitCode).toBe(1);

    const engine = createEngine({ dataDir });
    const state = engine.getTaskState("feat-run");
    expect(state?.status).toBe("blocked");
  });

  it("exits with the wrapped command exit code", () => {
    run([
      "emit", "test-run",
      "--task", "feat-run",
      "--signal-id", "sig-test",
      "--data-dir", dataDir,
      "--", "node", "-e", "process.exit(42)",
    ]);

    expect(process.exitCode).toBe(42);
  });
});
