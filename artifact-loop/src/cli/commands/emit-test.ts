// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import type { TestResultPayload } from "../../types.js";
import { resolveEngine } from "../helpers/engine-factory.js";
import { buildContext } from "../helpers/context.js";
import { formatTaskReference } from "../helpers/format.js";
import { buildRawArtifact } from "../helpers/raw-artifact.js";
import { resolveTaskId } from "../helpers/session.js";

export function registerEmitTest(emitCmd: Command): void {
  emitCmd
    .command("test")
    .description("Emit a test result artifact")
    .option("--task <id>", "Target task ID (defaults to current task)")
    .requiredOption("--signal-id <id>", "Acceptance signal ID to match")
    .option("--passed", "Test passed")
    .option("--failed", "Test failed")
    .option("--output <text>", "Test output text")
    .option("--worker <id>", "Worker ID (default: $USER)")
    .option("--data-dir <dir>", "Data directory")
    .action((opts: {
      task?: string;
      signalId: string;
      passed?: boolean;
      failed?: boolean;
      output?: string;
      worker?: string;
      dataDir?: string;
    }) => {
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

      if (!opts.passed && !opts.failed) {
        console.error("Must specify --passed or --failed");
        process.exitCode = 1;
        return;
      }
      if (opts.passed && opts.failed) {
        console.error("Cannot specify both --passed and --failed");
        process.exitCode = 1;
        return;
      }

      const passed = opts.passed === true;
      const payload: TestResultPayload = {
        type: "test_result",
        signal_id: opts.signalId,
        passed,
        output: opts.output,
      };

      const engine = resolveEngine(opts);
      const context = buildContext({ task: taskId, worker: opts.worker });
      const artifact = buildRawArtifact("test_result", payload, `Test ${passed ? "passed" : "failed"}`);
      const result = engine.ingest(artifact, context);

      const status = result.derivationOutput.nextState.status;
      const transition = result.derivationOutput.transitionOccurred;
      console.log(`Emitted test_result (${passed ? "passed" : "failed"}) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`);
    });
}
