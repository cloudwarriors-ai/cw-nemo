// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import type { ManualEventPayload } from "../../types.js";
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

const VALID_EVENT_TYPES = ["missing_input", "input_provided", "blocked", "context_note"] as const;
type EventType = typeof VALID_EVENT_TYPES[number];

export function registerEmitNote(emitCmd: Command): void {
  emitCmd
    .command("note")
    .description("Emit a manual event note")
    .option("--task <id>", "Target task ID (defaults to current task)")
    .requiredOption("--event-type <type>", `Event type: ${VALID_EVENT_TYPES.join("|")}`)
    .requiredOption("--description <text>", "Event description")
    .requiredOption("--by <who>", "Who is emitting this note")
    .option("--worker <id>", "Worker ID (default: $USER)")
    .option("--worker-agent <id>", "Worker agent ID")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action((opts: {
      task?: string;
      eventType: string;
      description: string;
      by: string;
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
        "emit note",
        resolved.taskId,
        resolved.contextSource,
        resolved.overrideSession,
      );
      const taskLabel = formatTaskReference(resolved.taskId, resolved.fromSession);

      if (!VALID_EVENT_TYPES.includes(opts.eventType as EventType)) {
        console.error(`Invalid event type: ${opts.eventType}. Must be one of: ${VALID_EVENT_TYPES.join(", ")}`);
        process.exitCode = 1;
        return;
      }

      const payload: ManualEventPayload = {
        type: "manual_event",
        event_type: opts.eventType,
        description: opts.description,
        by: opts.by,
      };

      const artifact = buildRawArtifact(
        "manual_event",
        payload,
        `Note: ${opts.eventType}`,
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
            console.log(`Emitted note (${opts.eventType}) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`);
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
      console.log(`Emitted note (${opts.eventType}) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`);
    });
}
