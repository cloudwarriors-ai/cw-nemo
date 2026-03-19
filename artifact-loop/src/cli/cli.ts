// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { Command } from "commander";
import { registerTaskStatus } from "./commands/task-status.js";
import { registerTaskHistory } from "./commands/task-history.js";
import { registerTaskUse } from "./commands/task-use.js";
import { registerTaskUnuse } from "./commands/task-unuse.js";
import { registerEmitTest } from "./commands/emit-test.js";
import { registerEmitTestRun } from "./commands/emit-test-run.js";
import { registerEmitNote } from "./commands/emit-note.js";
import { registerEmitMerge } from "./commands/emit-merge.js";

export function createProgram(): Command {
  const program = new Command();
  program
    .name("artifact-loop")
    .description("Artifact Loop v0.5 — task coordination via evidence-driven derivation")
    .version("0.1.0");

  // ─── task group ─────────────────────────────────────────────────
  const taskCmd = program.command("task").description("Inspect task state");
  registerTaskStatus(taskCmd);
  registerTaskHistory(taskCmd);
  registerTaskUse(taskCmd);
  registerTaskUnuse(taskCmd);

  // ─── emit group ─────────────────────────────────────────────────
  const emitCmd = program.command("emit").description("Emit evidence artifacts");
  registerEmitTest(emitCmd);
  registerEmitTestRun(emitCmd);
  registerEmitNote(emitCmd);
  registerEmitMerge(emitCmd);

  return program;
}

export function main(argv?: string[]): void {
  const program = createProgram();
  program.parse(argv ?? process.argv);
}
