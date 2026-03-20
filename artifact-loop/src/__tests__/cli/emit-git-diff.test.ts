// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { createEngine } from "../../engine.js";
import { createProgram } from "../../cli/cli.js";
import type { GitDiffSummaryPayload, TaskCreate } from "../../types.js";

let dataDir: string;
let repoDir: string;
let originalCwd: string;

function makeTask(): TaskCreate {
  return {
    id: "feat-git",
    title: "Git Diff Feature",
    description: "Test git diff emission",
    assignee_human_id: "chad",
    status: "not_started",
    acceptance_criteria: "git evidence captured",
    acceptance_signals: [
      { id: "sig-test", category: "test", required: true, success_condition: "tests pass", pattern: "*.test.ts" },
    ],
    depends_on: [],
  };
}

function runCli(args: string[]): string {
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
  dataDir = mkdtempSync(join(tmpdir(), "al-git-"));
  repoDir = mkdtempSync(join(tmpdir(), "al-git-repo-"));
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

describe("emit git-diff", () => {
  it("captures working_tree summary and does not change status", () => {
    writeFileSync(join(repoDir, "tracked.txt"), "modified\n", "utf-8");
    writeFileSync(join(repoDir, "new.txt"), "new\n", "utf-8");

    const output = runCli(["emit", "git-diff", "--task", "feat-git", "--data-dir", dataDir]);

    expect(output).toContain("Emitted git_diff_summary (working_tree, 2 file(s)) for feat-git");
    expect(output).toContain("status: not_started");

    const engine = createEngine({ dataDir });
    const state = engine.getTaskState("feat-git");
    expect(state?.status).toBe("not_started");

    const payload = engine.getArtifacts("feat-git")[0]?.signal_payload as GitDiffSummaryPayload;
    expect(payload.type).toBe("git_diff_summary");
    expect(payload.mode).toBe("working_tree");
    expect(payload.files).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ path: "tracked.txt", change_type: "modified" }),
        expect.objectContaining({ path: "new.txt", change_type: "created" }),
      ]),
    );
  });

  it("captures staged-only summary", () => {
    writeFileSync(join(repoDir, "tracked.txt"), "modified\n", "utf-8");
    git("add", "tracked.txt");
    writeFileSync(join(repoDir, "new.txt"), "new\n", "utf-8");

    const output = runCli(["emit", "git-diff", "--task", "feat-git", "--staged", "--data-dir", dataDir]);

    expect(output).toContain("Emitted git_diff_summary (staged, 1 file(s)) for feat-git");

    const engine = createEngine({ dataDir });
    const payload = engine.getArtifacts("feat-git")[0]?.signal_payload as GitDiffSummaryPayload;
    expect(payload.mode).toBe("staged");
    expect(payload.files).toEqual([
      expect.objectContaining({ path: "tracked.txt", change_type: "modified" }),
    ]);
  });
});
