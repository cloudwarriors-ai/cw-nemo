// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { resolve } from "node:path";
import type { Command } from "commander";
import { createEngine } from "../../engine.js";
import { createUsageStore, summarizeUsage } from "../../usage-store.js";
import { resolveArtifactLoopClient, resolveServiceUrl } from "../helpers/client.js";
import { formatJson, formatUsageStats } from "../helpers/format.js";

export function registerStats(program: Command): void {
  program
    .command("stats")
    .description("Show Artifact Loop usage stats")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action((opts: { json?: boolean; dataDir?: string; serviceUrl?: string }) => {
      if (resolveServiceUrl(opts)) {
        return (async () => {
          const client = resolveArtifactLoopClient(opts);
          try {
            const stats = await client.getStats();
            if (opts.json) {
              console.log(formatJson(stats));
            } else {
              console.log(formatUsageStats(stats));
            }
          } catch (err) {
            console.error((err as Error).message);
            process.exitCode = 1;
          }
        })();
      }

      const dataDir = resolve(opts.dataDir ?? ".artifact-loop");
      const engine = createEngine({ dataDir });
      const usageStore = createUsageStore(dataDir);
      const stats = summarizeUsage(
        usageStore.list(),
        engine.getTasks(),
        (taskId) => engine.getArtifacts(taskId),
      );

      if (opts.json) {
        console.log(formatJson(stats));
      } else {
        console.log(formatUsageStats(stats));
      }
    });
}
