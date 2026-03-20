// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { executeRunAction } from "./run.js";

export function registerEmitTestRun(emitCmd: Command): void {
  emitCmd
    .command("test-run")
    .description("Run a command and emit the result as a test artifact")
    .option("--task <id>", "Target task ID (defaults to current task)")
    .requiredOption("--signal-id <id>", "Acceptance signal ID to match")
    .option("--worker <id>", "Worker ID (default: $USER)")
    .option("--worker-agent <id>", "Worker agent ID")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .allowExcessArguments(true)
    .helpOption("-h, --help")
    .action((opts: {
      task?: string;
      signalId: string;
      worker?: string;
      workerAgent?: string;
      serviceUrl?: string;
      dataDir?: string;
    }, cmd: Command) => {
      const emitParent = cmd.parent as
        | (Command & { rawArgs?: string[]; parent?: Command & { rawArgs?: string[] } })
        | undefined;
      return executeRunAction(
        { ...opts, kind: "test" },
        "emit test-run",
        "artifact-loop emit test-run --signal-id <id> -- <command...>",
        emitParent?.parent?.rawArgs ?? emitParent?.rawArgs ?? process.argv,
      );
    });
}
