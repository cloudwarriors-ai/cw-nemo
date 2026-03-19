// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import type { ManualEventPayload } from "../../types.js";
import { resolveEngine } from "../helpers/engine-factory.js";
import { buildContext } from "../helpers/context.js";
import { formatTaskReference } from "../helpers/format.js";
import { buildRawArtifact } from "../helpers/raw-artifact.js";
import { resolveTaskId } from "../helpers/session.js";

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
    .option("--data-dir <dir>", "Data directory")
    .action((opts: {
      task?: string;
      eventType: string;
      description: string;
      by: string;
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

      const engine = resolveEngine(opts);
      const context = buildContext({ task: taskId, worker: opts.worker });
      const artifact = buildRawArtifact("manual_event", payload, `Note: ${opts.eventType}`);
      const result = engine.ingest(artifact, context);

      const status = result.derivationOutput.nextState.status;
      const transition = result.derivationOutput.transitionOccurred;
      console.log(`Emitted note (${opts.eventType}) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`);
    });
}
