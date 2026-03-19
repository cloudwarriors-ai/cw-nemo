// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveEngine } from "../helpers/engine-factory.js";
import { formatDerivationHistory, formatJson } from "../helpers/format.js";
import { resolveTaskId } from "../helpers/session.js";

export function registerTaskHistory(taskCmd: Command): void {
  taskCmd
    .command("history [task-id]")
    .description("Show derivation run history")
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

      const history = engine.getDerivationHistory(taskId);

      if (opts.json) {
        console.log(formatJson(history));
      } else {
        console.log(formatDerivationHistory(taskId, history, fromSession));
      }
    });
}
