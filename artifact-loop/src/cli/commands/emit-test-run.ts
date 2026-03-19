// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { spawnSync } from "node:child_process";
import type { TestResultPayload } from "../../types.js";
import { resolveEngine } from "../helpers/engine-factory.js";
import { buildContext } from "../helpers/context.js";
import { formatTaskReference } from "../helpers/format.js";
import { buildRawArtifact } from "../helpers/raw-artifact.js";
import { resolveTaskId } from "../helpers/session.js";

/** Keep last 2KB of output for artifact storage. */
function truncate(text: string, maxBytes: number = 2048): string {
  if (Buffer.byteLength(text, "utf-8") <= maxBytes) return text;
  const buf = Buffer.from(text, "utf-8");
  return buf.subarray(buf.length - maxBytes).toString("utf-8");
}

export function registerEmitTestRun(emitCmd: Command): void {
  emitCmd
    .command("test-run")
    .description("Run a command and emit the result as a test artifact")
    .option("--task <id>", "Target task ID (defaults to current task)")
    .requiredOption("--signal-id <id>", "Acceptance signal ID to match")
    .option("--worker <id>", "Worker ID (default: $USER)")
    .option("--data-dir <dir>", "Data directory")
    .allowExcessArguments(true)
    .helpOption("-h, --help")
    .action((opts: {
      task?: string;
      signalId: string;
      worker?: string;
      dataDir?: string;
    }, cmd: Command) => {
      let taskId: string;
      try {
        taskId = resolveTaskId(opts);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
        return;
      }
      const fromSession = !opts.task;
      const taskLabel = formatTaskReference(taskId, fromSession);

      // Everything after -- is the command to run
      const args = cmd.parent!.parent!.args;
      const dashIdx = process.argv.indexOf("--");
      if (dashIdx === -1) {
        console.error("Usage: artifact-loop emit test-run --task <id> --signal-id <id> -- <command...>");
        process.exitCode = 1;
        return;
      }

      const cmdArgs = process.argv.slice(dashIdx + 1);
      if (cmdArgs.length === 0) {
        console.error("No command specified after --");
        process.exitCode = 1;
        return;
      }

      const [command, ...commandArgs] = cmdArgs;

      // Run the command
      const result = spawnSync(command, commandArgs, {
        stdio: ["inherit", "pipe", "pipe"],
        encoding: "utf-8",
      });

      // Stream output to terminal
      if (result.stdout) process.stdout.write(result.stdout);
      if (result.stderr) process.stderr.write(result.stderr);

      const exitCode = result.status ?? 1;
      const passed = exitCode === 0;

      const payload: TestResultPayload = {
        type: "test_result",
        signal_id: opts.signalId,
        passed,
        output: truncate(result.stdout ?? ""),
        error: truncate(result.stderr ?? ""),
      };

      const engine = resolveEngine(opts);
      const context = buildContext({ task: taskId, worker: opts.worker });
      const artifact = buildRawArtifact("test_result", payload, `Test run: ${cmdArgs.join(" ")}`);
      const ingestResult = engine.ingest(artifact, context);

      const status = ingestResult.derivationOutput.nextState.status;
      const transition = ingestResult.derivationOutput.transitionOccurred;
      console.log(`\nEmitted test_result (${passed ? "passed" : "failed"}) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`);

      // Exit with wrapped command's exit code
      process.exitCode = exitCode;
    });
}
