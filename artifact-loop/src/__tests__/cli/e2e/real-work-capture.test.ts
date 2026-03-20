// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { createEngine } from "../../../engine.js";
import { createProgram } from "../../../cli/cli.js";
import type { TaskCreate } from "../../../types.js";

let dataDir: string;
let repoDir: string;
let originalCwd: string;

function makeTask(): TaskCreate {
  return {
    id: "feat-widget",
    title: "Widget Feature",
    description: "Build the widget",
    assignee_human_id: "chad",
    status: "not_started",
    acceptance_criteria: "tests pass",
    acceptance_signals: [
      { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
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

function git(...args: string[]): string {
  return execFileSync("git", args, { cwd: repoDir, encoding: "utf-8" });
}

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-real-work-"));
  repoDir = mkdtempSync(join(tmpdir(), "al-real-work-repo-"));
  originalCwd = process.cwd();
  process.chdir(repoDir);

  git("init");
  git("config", "user.email", "test@example.com");
  git("config", "user.name", "Test User");
  writeFileSync(join(repoDir, "tracked.txt"), "base\n", "utf-8");
  git("add", "tracked.txt");
  git("commit", "-m", "initial");

  const engine = createEngine({ dataDir });
  engine.createTask(makeTask());
});

afterEach(() => {
  process.chdir(originalCwd);
  rmSync(dataDir, { recursive: true, force: true });
  rmSync(repoDir, { recursive: true, force: true });
  process.exitCode = undefined;
});

describe("real work capture e2e", () => {
  it("tracks session-default run, git diff, and stats without git affecting status", () => {
    let out = run(["task", "use", "feat-widget", "--data-dir", dataDir]);
    expect(out).toContain("Now using task: feat-widget");

    out = run([
      "run",
      "--signal-id", "sig-test",
      "--data-dir", dataDir,
      "--", "node", "-e", "",
    ]);
    expect(out).toContain("for feat-widget (from session)");
    expect(out).toContain("ready_for_review");

    writeFileSync(join(repoDir, "tracked.txt"), "changed\n", "utf-8");
    writeFileSync(join(repoDir, "new.txt"), "new\n", "utf-8");

    out = run(["emit", "git-diff", "--data-dir", dataDir]);
    expect(out).toContain("for feat-widget (from session)");
    expect(out).toContain("status: ready_for_review");

    out = run(["task", "status", "--data-dir", dataDir]);
    expect(out).toContain("Task: feat-widget (from session)");
    expect(out).toContain("Status: ready_for_review");

    const stats = JSON.parse(run(["stats", "--json", "--data-dir", dataDir]));
    expect(stats.command_resolution.session_default).toBe(3);
    expect(stats.artifacts_by_type.test_result).toBe(1);
    expect(stats.artifacts_by_type.git_diff_summary).toBe(1);
    expect(stats.evidence_buckets.automatic_any).toBe(1);
  });
});
