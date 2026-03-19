// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import type { MergeResultPayload } from "../../types.js";
import { resolveEngine } from "../helpers/engine-factory.js";
import { buildContext } from "../helpers/context.js";
import { formatTaskReference } from "../helpers/format.js";
import { buildRawArtifact } from "../helpers/raw-artifact.js";
import { resolveTaskId } from "../helpers/session.js";

export function registerEmitMerge(emitCmd: Command): void {
  emitCmd
    .command("merge")
    .description("Emit a merge result artifact")
    .option("--task <id>", "Target task ID (defaults to current task)")
    .requiredOption("--signal-id <id>", "Acceptance signal ID to match")
    .requiredOption("--ref <ref>", "Merge commit ref")
    .requiredOption("--branch <branch>", "Target branch")
    .option("--worker <id>", "Worker ID (default: $USER)")
    .option("--data-dir <dir>", "Data directory")
    .action((opts: {
      task?: string;
      signalId: string;
      ref: string;
      branch: string;
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

      const payload: MergeResultPayload = {
        type: "merge_result",
        signal_id: opts.signalId,
        merge_ref: opts.ref,
        target_branch: opts.branch,
      };

      const engine = resolveEngine(opts);
      const context = buildContext({ task: taskId, worker: opts.worker });
      const artifact = buildRawArtifact("merge_result", payload, `Merge ${opts.ref} → ${opts.branch}`);
      const result = engine.ingest(artifact, context);

      const status = result.derivationOutput.nextState.status;
      const transition = result.derivationOutput.transitionOccurred;
      console.log(`Emitted merge_result for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`);
    });
}
