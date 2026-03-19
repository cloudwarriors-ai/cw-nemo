// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { resolve } from "node:path";
import type { Command } from "commander";
import { getSession, setSession } from "../helpers/session.js";

export function registerTaskUse(taskCmd: Command): void {
  taskCmd
    .command("use [task-id]")
    .description("Set or show the current task for this session")
    .option("--data-dir <dir>", "Data directory")
    .action((taskId: string | undefined, opts: { dataDir?: string }) => {
      const dataDir = resolve(opts.dataDir ?? ".artifact-loop");

      if (!taskId) {
        // Show current task
        const session = getSession(dataDir);
        if (session?.current_task_id) {
          console.log(`Current task: ${session.current_task_id}`);
        } else {
          console.log("No current task");
        }
        return;
      }

      // Set current task (validates existence)
      try {
        setSession(dataDir, taskId);
        console.log(`Now using task: ${taskId}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
