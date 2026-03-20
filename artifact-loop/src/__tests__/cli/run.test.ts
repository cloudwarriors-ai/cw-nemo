// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createEngine } from "../../engine.js";
import { createProgram } from "../../cli/cli.js";
import { setSession } from "../../cli/helpers/session.js";
import type { TaskCreate } from "../../types.js";

let dataDir: string;

function makeTask(overrides?: Partial<TaskCreate>): TaskCreate {
  return {
    id: "feat-run",
    title: "Run Feature",
    description: "Exercise the generic run command",
    assignee_human_id: "chad",
    status: "not_started",
    acceptance_criteria: "task evidence exists",
    acceptance_signals: [
      { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
    ],
    depends_on: [],
    ...overrides,
  };
}

function runCli(args: string[]): { stdout: string; stderr: string; logs: string } {
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
  vi.spyOn(console, "error").mockImplementation((...a: unknown[]) => stderr.push(String(a[0])));

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
  dataDir = mkdtempSync(join(tmpdir(), "al-run-generic-"));
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
  process.exitCode = undefined;
});

describe("artifact-loop run", () => {
  it("emits test_result and preserves session-default source tracking", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask());
    setSession(dataDir, "feat-run");

    const result = runCli([
      "run",
      "--signal-id", "sig-test",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('ok from run')",
    ]);

    expect(result.stdout).toContain("ok from run");
    expect(result.logs).toContain("Emitted test_result (passed) for feat-run (from session)");
    expect(result.logs).toContain("ready_for_review");

    const state = engine.getTaskState("feat-run");
    expect(state?.status).toBe("ready_for_review");

    const usage = readFileSync(join(dataDir, "usage/events.jsonl"), "utf-8");
    expect(usage).toContain('"context_source":"session_default"');
  });

  it("emits command_result without changing status when no matching command signal exists", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask());

    const result = runCli([
      "run",
      "--task", "feat-run",
      "--signal-id", "sig-command",
      "--kind", "command",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('command ok')",
    ]);

    expect(result.stdout).toContain("command ok");
    expect(result.logs).toContain("Emitted command_result (exit 0) for feat-run");

    const state = engine.getTaskState("feat-run");
    expect(state?.status).toBe("not_started");
    const artifact = engine.getArtifacts("feat-run")[0];
    expect(artifact?.signal_payload.type).toBe("command_result");
  });

  it("uses existing command signal rules and nothing more", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask({
      acceptance_signals: [
        { id: "sig-command", category: "command", required: true, success_condition: "exit code 0", command: "node -e" },
      ],
    }));

    const result = runCli([
      "run",
      "--task", "feat-run",
      "--signal-id", "sig-command",
      "--kind", "command",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('command passes')",
    ]);

    expect(result.logs).toContain("Emitted command_result (exit 0) for feat-run");
    expect(result.logs).toContain("ready_for_review");

    const state = engine.getTaskState("feat-run");
    expect(state?.status).toBe("ready_for_review");
  });

  it("resolves the next runnable required test signal", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask());
    setSession(dataDir, "feat-run");

    const result = runCli([
      "run",
      "--next",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('next test run')",
    ]);

    expect(result.stdout).toContain("next test run");
    expect(result.logs).toContain("Using next signal: sig-test (test, required)");
    expect(result.logs).toContain("Emitted test_result (passed) for feat-run (from session)");
    expect(engine.getTaskState("feat-run")?.status).toBe("ready_for_review");
  });

  it("resolves the next runnable required command signal", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask({
      acceptance_signals: [
        { id: "sig-command", category: "command", required: true, success_condition: "exit code 0", command: "node -e" },
      ],
    }));

    const result = runCli([
      "run",
      "--task", "feat-run",
      "--next",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('next command run')",
    ]);

    expect(result.stdout).toContain("next command run");
    expect(result.logs).toContain("Using next signal: sig-command (command, required)");
    expect(result.logs).toContain("Emitted command_result (exit 0) for feat-run");
    expect(engine.getTaskState("feat-run")?.status).toBe("ready_for_review");
  });

  it("prefers explicit task over session when resolving --next", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask());
    engine.createTask({
      ...makeTask(),
      id: "feat-other",
      title: "Other Run Feature",
      acceptance_signals: [
        { id: "sig-other", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
      ],
    });
    setSession(dataDir, "feat-run");

    const result = runCli([
      "run",
      "--task", "feat-other",
      "--next",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('explicit task wins')",
    ]);

    expect(result.logs).toContain("Using next signal: sig-other (test, required)");
    expect(result.logs).toContain("Emitted test_result (passed) for feat-other");
    expect(engine.getTaskState("feat-other")?.status).toBe("ready_for_review");
    expect(engine.getTaskState("feat-run")?.status).toBe("not_started");
  });

  it("errors when --next has no current task", () => {
    const result = runCli([
      "run",
      "--next",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('should not run')",
    ]);

    expect(result.stderr).toContain("No task specified. Use --task <id> or run: artifact-loop task use <id>");
    expect(result.stdout).not.toContain("should not run");
  });

  it("errors when no unsatisfied runnable required signal exists", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask());
    runCli([
      "run",
      "--task", "feat-run",
      "--signal-id", "sig-test",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('satisfy test')",
    ]);

    const result = runCli([
      "run",
      "--task", "feat-run",
      "--next",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('should not rerun')",
    ]);

    expect(result.stderr).toContain("No unsatisfied runnable required signal found for feat-run. Run: artifact-loop task status feat-run");
    expect(result.stdout).not.toContain("should not rerun");
    expect(engine.getArtifacts("feat-run")).toHaveLength(1);
  });

  it("errors when only non-runnable required signals remain", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask({
      acceptance_signals: [
        { id: "sig-merge", category: "merge", required: true, success_condition: "merged to main" },
      ],
    }));

    const result = runCli([
      "run",
      "--task", "feat-run",
      "--next",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('should not run merge')",
    ]);

    expect(result.stderr).toContain("No unsatisfied runnable required signal found for feat-run. Run: artifact-loop task status feat-run");
    expect(result.stdout).not.toContain("should not run merge");
    expect(engine.getArtifacts("feat-run")).toHaveLength(0);
  });

  it("errors when multiple runnable required signals are unsatisfied", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask({
      acceptance_signals: [
        { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
        { id: "sig-command", category: "command", required: true, success_condition: "exit code 0", command: "node -e" },
      ],
    }));

    const result = runCli([
      "run",
      "--task", "feat-run",
      "--next",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('ambiguous should not run')",
    ]);

    expect(result.stderr).toContain("Multiple runnable required signals are unsatisfied for feat-run: sig-test (test), sig-command (command). Run: artifact-loop task status feat-run");
    expect(result.stdout).not.toContain("ambiguous should not run");
    expect(engine.getArtifacts("feat-run")).toHaveLength(0);
  });

  it("fails validation when --next and --signal-id are both provided", () => {
    const engine = createEngine({ dataDir });
    engine.createTask(makeTask());

    const result = runCli([
      "run",
      "--task", "feat-run",
      "--next",
      "--signal-id", "sig-test",
      "--data-dir", dataDir,
      "--", "node", "-e", "console.log('invalid flags')",
    ]);

    expect(result.stderr).toContain("Cannot use --next with --signal-id. Use one or the other.");
    expect(result.stdout).not.toContain("invalid flags");
    expect(engine.getArtifacts("feat-run")).toHaveLength(0);
  });
});
