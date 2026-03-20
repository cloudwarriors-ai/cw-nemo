// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { execFileSync } from "node:child_process";
import type { GitDiffSummaryFile, GitDiffSummaryPayload } from "../../types.js";

function mapChangeCode(code: string): GitDiffSummaryFile["change_type"] {
  if (code.includes("?") || code.includes("A")) return "created";
  if (code.includes("D")) return "deleted";
  return "modified";
}

function parseStaged(output: string): GitDiffSummaryFile[] {
  const tokens = output.split("\0").filter(Boolean);
  const files: GitDiffSummaryFile[] = [];

  for (let i = 0; i < tokens.length; i += 2) {
    const status = tokens[i]!;
    const firstPath = tokens[i + 1];
    if (!firstPath) continue;

    if (status.startsWith("R") || status.startsWith("C")) {
      const nextPath = tokens[i + 2];
      files.push({
        path: nextPath ?? firstPath,
        previous_path: firstPath,
        change_type: "modified",
      });
      i += 1;
      continue;
    }

    files.push({
      path: firstPath,
      change_type: mapChangeCode(status),
    });
  }

  return files;
}

function parseWorkingTree(output: string): GitDiffSummaryFile[] {
  const tokens = output.split("\0").filter(Boolean);
  const files: GitDiffSummaryFile[] = [];

  for (let i = 0; i < tokens.length; i += 1) {
    const entry = tokens[i]!;
    if (entry.length < 4) continue;

    const status = entry.slice(0, 2);
    const firstPath = entry.slice(3);
    if (status.includes("R") || status.includes("C")) {
      const nextPath = tokens[i + 1];
      files.push({
        path: nextPath ?? firstPath,
        previous_path: firstPath,
        change_type: "modified",
      });
      i += 1;
      continue;
    }

    files.push({
      path: firstPath,
      change_type: mapChangeCode(status),
    });
  }

  return files;
}

export function buildGitDiffPayload(mode: "working_tree" | "staged"): GitDiffSummaryPayload {
  if (mode === "staged") {
    const output = execFileSync(
      "git",
      ["diff", "--cached", "--name-status", "-z", "--find-renames"],
      { encoding: "utf-8" },
    );
    return {
      type: "git_diff_summary",
      mode,
      files: parseStaged(output),
    };
  }

  const output = execFileSync(
    "git",
    ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
    { encoding: "utf-8" },
  );
  return {
    type: "git_diff_summary",
    mode,
    files: parseWorkingTree(output),
  };
}
