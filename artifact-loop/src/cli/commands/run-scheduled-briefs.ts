// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveEngine } from "../helpers/engine-factory.js";
import { formatJson } from "../helpers/format.js";

export function registerRunScheduledBriefs(program: Command): void {
  program
    .command("run-scheduled-briefs")
    .description("Generate due scheduled project briefs")
    .option("--json", "Output as JSON")
    .option("--data-dir <dir>", "Data directory")
    .action((opts: { json?: boolean; dataDir?: string }) => {
      try {
        const engine = resolveEngine(opts);
        const result = engine.runScheduledBriefs();
        console.log(opts.json ? formatJson(result) : `Generated ${result.generated_count} scheduled brief(s)`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
