// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import type { TestResultPayload } from "../../types.js";
import {
  resolveArtifactLoopClient,
  resolveArtifactSource,
  resolveServiceUrl,
} from "../helpers/client.js";
import { resolveEngine } from "../helpers/engine-factory.js";
import { buildContext } from "../helpers/context.js";
import { formatTaskReference } from "../helpers/format.js";
import { buildRawArtifact } from "../helpers/raw-artifact.js";
import { resolveTaskTarget } from "../helpers/session.js";
import { recordCommandResolution } from "../helpers/usage.js";

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
    .option("--worker-agent <id>", "Worker agent ID")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action((opts: {
      task?: string;
      signalId: string;
      passed?: boolean;
      failed?: boolean;
      output?: string;
      worker?: string;
      workerAgent?: string;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      let resolved;
      try {
        resolved = resolveTaskTarget(opts);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
        return;
      }
      recordCommandResolution(
        opts.dataDir ?? ".artifact-loop",
        "emit test",
        resolved.taskId,
        resolved.contextSource,
        resolved.overrideSession,
      );
      const taskLabel = formatTaskReference(resolved.taskId, resolved.fromSession);

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

      const artifact = buildRawArtifact(
        "test_result",
        payload,
        `Test ${passed ? "passed" : "failed"}`,
        resolveArtifactSource(opts),
      );
      const context = buildContext({
        task: resolved.taskId,
        worker: opts.worker,
        workerAgent: opts.workerAgent,
        fromSession: resolved.fromSession,
      });

      if (resolveServiceUrl(opts)) {
        return (async () => {
          const client = resolveArtifactLoopClient(opts);
          try {
            const result = await client.ingest({ artifact, context });
            const status = result.derivationOutput.nextState.status;
            const transition = result.derivationOutput.transitionOccurred;
            console.log(`Emitted test_result (${passed ? "passed" : "failed"}) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`);
          } catch (err) {
            console.error((err as Error).message);
            process.exitCode = 1;
          }
        })();
      }

      const engine = resolveEngine(opts);
      const result = engine.ingest(artifact, context);

      const status = result.derivationOutput.nextState.status;
      const transition = result.derivationOutput.transitionOccurred;
      console.log(`Emitted test_result (${passed ? "passed" : "failed"}) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`);
    });
}
