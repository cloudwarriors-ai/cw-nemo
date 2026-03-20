// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import {
  resolveArtifactLoopClient,
  resolveArtifactSource,
  resolveServiceUrl,
} from "../helpers/client.js";
import { resolveEngine } from "../helpers/engine-factory.js";
import { buildContext } from "../helpers/context.js";
import { formatTaskReference } from "../helpers/format.js";
import { buildGitDiffPayload } from "../helpers/git-diff.js";
import { buildRawArtifact } from "../helpers/raw-artifact.js";
import { resolveTaskTarget } from "../helpers/session.js";
import { recordCommandResolution } from "../helpers/usage.js";

export function registerEmitGitDiff(emitCmd: Command): void {
  emitCmd
    .command("git-diff")
    .description("Emit a git diff summary artifact")
    .option("--task <id>", "Target task ID (defaults to current task)")
    .option("--staged", "Capture staged changes only")
    .option("--worker <id>", "Worker ID (default: $USER)")
    .option("--worker-agent <id>", "Worker agent ID")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action((opts: {
      task?: string;
      staged?: boolean;
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
        "emit git-diff",
        resolved.taskId,
        resolved.contextSource,
        resolved.overrideSession,
      );

      const mode = opts.staged ? "staged" : "working_tree";
      let payload;
      try {
        payload = buildGitDiffPayload(mode);
      } catch (err) {
        console.error(`Failed to capture git diff: ${(err as Error).message}`);
        process.exitCode = 1;
        return;
      }

      const artifact = buildRawArtifact(
        "git_diff_summary",
        payload,
        `Git diff (${mode}): ${payload.files.length} file(s)`,
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
            const taskLabel = formatTaskReference(resolved.taskId, resolved.fromSession);
            const status = result.derivationOutput.nextState.status;
            const transition = result.derivationOutput.transitionOccurred;
            console.log(
              `Emitted git_diff_summary (${mode}, ${payload.files.length} file(s)) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`,
            );
          } catch (err) {
            console.error((err as Error).message);
            process.exitCode = 1;
          }
        })();
      }

      const engine = resolveEngine(opts);
      const result = engine.ingest(artifact, context);

      const taskLabel = formatTaskReference(resolved.taskId, resolved.fromSession);
      const status = result.derivationOutput.nextState.status;
      const transition = result.derivationOutput.transitionOccurred;
      console.log(
        `Emitted git_diff_summary (${mode}, ${payload.files.length} file(s)) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`,
      );
    });
}
