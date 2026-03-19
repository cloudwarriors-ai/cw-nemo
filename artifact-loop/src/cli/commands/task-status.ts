// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveEngine } from "../helpers/engine-factory.js";
import { formatJson, formatTaskStatus } from "../helpers/format.js";
import { resolveTaskId } from "../helpers/session.js";

export function registerTaskStatus(taskCmd: Command): void {
  taskCmd
    .command("status [task-id]")
    .description("Show task status and derived state")
    .option("--json", "Output as JSON")
    .option("--data-dir <dir>", "Data directory")
    .action((taskIdArg: string | undefined, opts: { json?: boolean; dataDir?: string }) => {
      const fromSession = !taskIdArg;
      let taskId: string;
      try {
        taskId = resolveTaskId({ task: taskIdArg, dataDir: opts.dataDir });
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
        return;
      }

      const engine = resolveEngine(opts);
      const task = engine.getTask(taskId);
      if (!task) {
        console.error(`Task not found: ${taskId}`);
        process.exitCode = 1;
        return;
      }

      const state = engine.getTaskState(taskId);
      if (!state) {
        console.error(`No state for task: ${taskId}`);
        process.exitCode = 1;
        return;
      }

      if (opts.json) {
        console.log(formatJson({ task, state }));
      } else {
        console.log(formatTaskStatus(task, state, fromSession));
      }
    });
}
