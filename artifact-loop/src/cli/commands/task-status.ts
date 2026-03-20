// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { evaluateSignalStatuses } from "../../derive.js";
import { resolveArtifactLoopClient, resolveServiceUrl } from "../helpers/client.js";
import { resolveEngine } from "../helpers/engine-factory.js";
import { formatJson, formatTaskStatus } from "../helpers/format.js";
import { resolveTaskTarget } from "../helpers/session.js";
import { recordCommandResolution } from "../helpers/usage.js";

export function registerTaskStatus(taskCmd: Command): void {
  taskCmd
    .command("status [task-id]")
    .description("Show task status and derived state")
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
        "task status",
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
            const state = await client.getTaskState(resolved.taskId);
            if (!state) {
              console.error(`No state for task: ${resolved.taskId}`);
              process.exitCode = 1;
              return;
            }

            if (opts.json) {
              console.log(formatJson({ task, state }));
            } else {
              const signalStatuses = evaluateSignalStatuses(
                task.acceptance_signals,
                await client.getTaskArtifacts(resolved.taskId),
              );
              console.log(formatTaskStatus(task, state, resolved.fromSession, signalStatuses));
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

      const state = engine.getTaskState(resolved.taskId);
      if (!state) {
        console.error(`No state for task: ${resolved.taskId}`);
        process.exitCode = 1;
        return;
      }

      if (opts.json) {
        console.log(formatJson({ task, state }));
      } else {
        const signalStatuses = evaluateSignalStatuses(
          task.acceptance_signals,
          engine.getArtifacts(resolved.taskId),
        );
        console.log(formatTaskStatus(task, state, resolved.fromSession, signalStatuses));
      }
    });
}
