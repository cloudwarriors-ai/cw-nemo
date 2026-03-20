// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { Command } from "commander";
import { registerTaskStatus } from "./commands/task-status.js";
import { registerTaskHistory } from "./commands/task-history.js";
import { registerTaskUse } from "./commands/task-use.js";
import { registerTaskUnuse } from "./commands/task-unuse.js";
import { registerTaskCoordination } from "./commands/task-coordination.js";
import { registerEmitTest } from "./commands/emit-test.js";
import { registerEmitTestRun } from "./commands/emit-test-run.js";
import { registerEmitNote } from "./commands/emit-note.js";
import { registerEmitMerge } from "./commands/emit-merge.js";
import { registerEmitGitDiff } from "./commands/emit-git-diff.js";
import { registerRun } from "./commands/run.js";
import { registerRunScheduledBriefs } from "./commands/run-scheduled-briefs.js";
import { registerServe } from "./commands/serve.js";
import { registerStats } from "./commands/stats.js";
import { registerInviteCommands } from "./commands/invite-commands.js";
import { registerProjectCommands } from "./commands/project-commands.js";
import { registerOrgCommands } from "./commands/org-commands.js";
import { registerTeamCommands } from "./commands/team-commands.js";
import { registerWorkerCommands } from "./commands/worker-commands.js";

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
  registerTaskCoordination(taskCmd);

  // ─── emit group ─────────────────────────────────────────────────
  const emitCmd = program.command("emit").description("Emit evidence artifacts");
  registerEmitTest(emitCmd);
  registerEmitTestRun(emitCmd);
  registerEmitNote(emitCmd);
  registerEmitMerge(emitCmd);
  registerEmitGitDiff(emitCmd);

  registerRun(program);
  registerRunScheduledBriefs(program);
  registerServe(program);
  registerStats(program);
  registerInviteCommands(program);
  registerOrgCommands(program);
  registerTeamCommands(program);
  registerProjectCommands(program);
  registerWorkerCommands(program);

  return program;
}

export async function main(argv?: string[]): Promise<void> {
  const program = createProgram();
  await program.parseAsync(argv ?? process.argv);
}
