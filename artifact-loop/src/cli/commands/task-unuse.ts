// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { resolve } from "node:path";
import type { Command } from "commander";
import { clearSession } from "../helpers/session.js";

export function registerTaskUnuse(taskCmd: Command): void {
  taskCmd
    .command("unuse")
    .description("Clear the current task session")
    .option("--data-dir <dir>", "Data directory")
    .action((opts: { dataDir?: string }) => {
      const dataDir = resolve(opts.dataDir ?? ".artifact-loop");
      clearSession(dataDir);
      console.log("Cleared current task");
    });
}
