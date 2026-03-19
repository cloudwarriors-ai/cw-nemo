// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { createEngine } from "../../engine.js";
import type { TaskCreate } from "../../types.js";

let dataDir: string;

const CLI_PATH = join(import.meta.dirname, "../../../bin/artifact-loop.js");

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

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-run-"));
  const engine = createEngine({ dataDir });
  engine.createTask(makeTask());
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
});

describe("emit test-run", () => {
  it("captures a passing command", () => {
    const result = execFileSync("node", [
      CLI_PATH, "emit", "test-run",
      "--task", "feat-run",
      "--signal-id", "sig-test",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('hello')",
    ], { encoding: "utf-8" });

    expect(result).toContain("hello");
    expect(result).toContain("passed");
    expect(result).toContain("for feat-run");
    expect(result).not.toContain("(from session)");
    expect(result).toContain("ready_for_review");

    const engine = createEngine({ dataDir });
    const state = engine.getTaskState("feat-run");
    expect(state?.status).toBe("ready_for_review");
  });

  it("captures a failing command", () => {
    let output = "";
    try {
      execFileSync("node", [
        CLI_PATH, "emit", "test-run",
        "--task", "feat-run",
        "--signal-id", "sig-test",
        "--data-dir", dataDir,
        "--", "node", "-e", "process.exit(1)",
      ], { encoding: "utf-8" });
    } catch (err: unknown) {
      const error = err as { status: number; stdout: string; stderr: string };
      expect(error.status).toBe(1);
      output = error.stdout + error.stderr;
    }

    expect(output).toContain("failed");
    expect(output).toContain("for feat-run");
    expect(output).not.toContain("(from session)");
    expect(output).toContain("blocked");

    const engine = createEngine({ dataDir });
    const state = engine.getTaskState("feat-run");
    expect(state?.status).toBe("blocked");
  });

  it("exits with the wrapped command exit code", () => {
    try {
      execFileSync("node", [
        CLI_PATH, "emit", "test-run",
        "--task", "feat-run",
        "--signal-id", "sig-test",
        "--data-dir", dataDir,
        "--", "node", "-e", "process.exit(42)",
      ], { encoding: "utf-8" });
      expect.unreachable("Should have thrown");
    } catch (err: unknown) {
      const error = err as { status: number };
      expect(error.status).toBe(42);
    }
  });
});
