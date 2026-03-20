// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveArtifactLoopClient, resolveServiceUrl } from "../helpers/client.js";
import { resolveEngine } from "../helpers/engine-factory.js";
import { formatDerivationHistory, formatJson } from "../helpers/format.js";
import { resolveTaskTarget } from "../helpers/session.js";
import { recordCommandResolution } from "../helpers/usage.js";

export function registerTaskHistory(taskCmd: Command): void {
  taskCmd
    .command("history [task-id]")
    .description("Show derivation run history")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action((taskIdArg: string | undefined, opts: { json?: boolean; dataDir?: string; serviceUrl?: string }) => {
      let resolved;
      try {
        resolved = resolveTaskTarget({ task: taskIdArg, dataDir: opts.dataDir });
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
        return;
      }
      recordCommandResolution(
        opts.dataDir ?? ".artifact-loop",
        "task history",
        resolved.taskId,
        resolved.contextSource,
        resolved.overrideSession,
      );

      if (resolveServiceUrl(opts)) {
        return (async () => {
          const client = resolveArtifactLoopClient(opts);
          try {
            const task = await client.getTask(resolved.taskId);
            if (!task) {
              console.error(`Task not found: ${resolved.taskId}`);
              process.exitCode = 1;
              return;
            }

            const history = await client.getTaskHistory(resolved.taskId);
            if (opts.json) {
              console.log(formatJson(history));
            } else {
              console.log(formatDerivationHistory(resolved.taskId, history, resolved.fromSession));
            }
          } catch (err) {
            console.error((err as Error).message);
            process.exitCode = 1;
          }
        })();
      }

      const engine = resolveEngine(opts);
      const task = engine.getTask(resolved.taskId);
      if (!task) {
        console.error(`Task not found: ${resolved.taskId}`);
        process.exitCode = 1;
        return;
      }

      const history = engine.getDerivationHistory(resolved.taskId);

      if (opts.json) {
        console.log(formatJson(history));
      } else {
        console.log(formatDerivationHistory(resolved.taskId, history, resolved.fromSession));
      }
    });
}
