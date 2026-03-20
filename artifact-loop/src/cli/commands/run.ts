// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import type { NormalizedArtifact, Task } from "../../types.js";
import {
  resolveArtifactLoopClient,
  resolveArtifactSource,
  resolveServiceUrl,
} from "../helpers/client.js";
import { buildContext } from "../helpers/context.js";
import { resolveEngine } from "../helpers/engine-factory.js";
import { formatTaskReference } from "../helpers/format.js";
import { buildRawArtifact } from "../helpers/raw-artifact.js";
import {
  captureRunArtifact,
  extractWrappedCommand,
  resolveNextRunnableSignal,
  type RunnableSignalKind,
} from "../helpers/run-command.js";
import { resolveTaskTarget, type ResolvedTaskTarget } from "../helpers/session.js";
import { recordCommandResolution } from "../helpers/usage.js";

interface RunOpts {
  task?: string;
  signalId?: string;
  next?: boolean;
  kind?: "test" | "command";
  worker?: string;
  workerAgent?: string;
  serviceUrl?: string;
  dataDir?: string;
}

function buildTaskStatusCommand(taskId: string, fromSession: boolean): string {
  return fromSession ? "artifact-loop task status" : `artifact-loop task status ${taskId}`;
}

function reportResolutionFailure(resolved: ResolvedTaskTarget, candidates: { id: string; category: string }[]): void {
  const taskLabel = formatTaskReference(resolved.taskId, resolved.fromSession);
  const taskStatusCommand = buildTaskStatusCommand(resolved.taskId, resolved.fromSession);

  if (candidates.length > 1) {
    const candidateList = candidates
      .map((candidate) => `${candidate.id} (${candidate.category})`)
      .join(", ");
    console.error(
      `Multiple runnable required signals are unsatisfied for ${taskLabel}: ${candidateList}. Run: ${taskStatusCommand}`,
    );
    return;
  }

  console.error(
    `No unsatisfied runnable required signal found for ${taskLabel}. Run: ${taskStatusCommand}`,
  );
}

function emitRunResult(
  kind: RunnableSignalKind,
  exitCode: number,
  taskLabel: string,
  status: string,
  transition: boolean,
): void {
  if (kind === "test") {
    console.log(
      `\nEmitted test_result (${exitCode === 0 ? "passed" : "failed"}) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`,
    );
    return;
  }

  console.log(
    `\nEmitted command_result (exit ${exitCode}) for ${taskLabel} → status: ${status}${transition ? " (transition)" : ""}`,
  );
}

function resolveLocalSignalSelection(
  opts: RunOpts,
  resolved: ResolvedTaskTarget,
  task: Task,
  getArtifacts: () => NormalizedArtifact[],
): { signalId: string; kind: RunnableSignalKind } | undefined {
  if (!opts.next) {
    if (!opts.signalId) {
      console.error("Missing required option: --signal-id <id> or use --next");
      process.exitCode = 1;
      return undefined;
    }
    return {
      signalId: opts.signalId,
      kind: opts.kind ?? "test",
    };
  }

  const resolution = resolveNextRunnableSignal(task, getArtifacts());
  if (!resolution.ok) {
    reportResolutionFailure(resolved, resolution.candidates);
    process.exitCode = 1;
    return undefined;
  }

  if (opts.kind && opts.kind !== resolution.kind) {
    console.error(
      `Resolved next signal ${resolution.signalId} requires kind=${resolution.kind}, but received --kind ${opts.kind}.`,
    );
    process.exitCode = 1;
    return undefined;
  }

  console.log(`Using next signal: ${resolution.signalId} (${resolution.kind}, required)`);
  return {
    signalId: resolution.signalId,
    kind: resolution.kind,
  };
}

export function executeRunAction(
  opts: RunOpts,
  commandName: string,
  usageText: string,
  argv: string[] = process.argv,
): void | Promise<void> {
  let resolved: ResolvedTaskTarget;
  try {
    resolved = resolveTaskTarget(opts);
  } catch (err) {
    console.error((err as Error).message);
    process.exitCode = 1;
    return;
  }

  if (opts.next && opts.signalId) {
    console.error("Cannot use --next with --signal-id. Use one or the other.");
    process.exitCode = 1;
    return;
  }

  recordCommandResolution(
    opts.dataDir ?? ".artifact-loop",
    commandName,
    resolved.taskId,
    resolved.contextSource,
    resolved.overrideSession,
  );

  let commandArgs: string[];
  try {
    commandArgs = extractWrappedCommand(argv);
  } catch (err) {
    console.error((err as Error).message.replace("artifact-loop run", usageText));
    process.exitCode = 1;
    return;
  }

  const taskLabel = formatTaskReference(resolved.taskId, resolved.fromSession);
  if (resolveServiceUrl(opts)) {
    return (async () => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const task = await client.getTask(resolved.taskId);
        if (!task) {
          console.error(`Task not found: ${resolved.taskId}`);
          process.exitCode = 1;
          return;
        }

        let signalId: string;
        let kind: RunnableSignalKind;
        if (opts.next) {
          const resolution = resolveNextRunnableSignal(task, await client.getTaskArtifacts(resolved.taskId));
          if (!resolution.ok) {
            reportResolutionFailure(resolved, resolution.candidates);
            process.exitCode = 1;
            return;
          }

          if (opts.kind && opts.kind !== resolution.kind) {
            console.error(
              `Resolved next signal ${resolution.signalId} requires kind=${resolution.kind}, but received --kind ${opts.kind}.`,
            );
            process.exitCode = 1;
            return;
          }

          signalId = resolution.signalId;
          kind = resolution.kind;
          console.log(`Using next signal: ${signalId} (${kind}, required)`);
        } else {
          const selection = resolveLocalSignalSelection(
            opts,
            resolved,
            task,
            () => [],
          );
          if (!selection) {
            return;
          }
          signalId = selection.signalId;
          kind = selection.kind;
        }

        const capture = captureRunArtifact(signalId, kind, commandArgs);
        const artifact = buildRawArtifact(
          kind === "test" ? "test_result" : "command_result",
          capture.payload,
          capture.summary,
          resolveArtifactSource(opts),
        );
        const context = buildContext({
          task: resolved.taskId,
          worker: opts.worker,
          workerAgent: opts.workerAgent,
          fromSession: resolved.fromSession,
        });

        try {
          const ingestResult = await client.ingest({ artifact, context });
          emitRunResult(
            kind,
            capture.exitCode,
            taskLabel,
            ingestResult.derivationOutput.nextState.status,
            ingestResult.derivationOutput.transitionOccurred,
          );
          process.exitCode = capture.exitCode;
        } catch (err) {
          console.error((err as Error).message);
          process.exitCode = 1;
        }
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    })();
  }

  const engine = resolveEngine(opts);
  const task = engine.getTask(resolved.taskId);
  if (!task) {
    console.error(`Task not found: ${resolved.taskId}`);
    process.exitCode = 1;
    return;
  }

  const selection = resolveLocalSignalSelection(
    opts,
    resolved,
    task,
    () => engine.getArtifacts(resolved.taskId),
  );
  if (!selection) {
    return;
  }

  const capture = captureRunArtifact(selection.signalId, selection.kind, commandArgs);
  const artifact = buildRawArtifact(
    selection.kind === "test" ? "test_result" : "command_result",
    capture.payload,
    capture.summary,
    resolveArtifactSource(opts),
  );
  const context = buildContext({
    task: resolved.taskId,
    worker: opts.worker,
    workerAgent: opts.workerAgent,
    fromSession: resolved.fromSession,
  });
  const ingestResult = engine.ingest(artifact, context);

  emitRunResult(
    selection.kind,
    capture.exitCode,
    taskLabel,
    ingestResult.derivationOutput.nextState.status,
    ingestResult.derivationOutput.transitionOccurred,
  );
  process.exitCode = capture.exitCode;
}

export function registerRun(program: Command): void {
  program
    .command("run")
    .description("Run a command and emit the result as task-bound evidence")
    .option("--task <id>", "Target task ID (defaults to current task)")
    .option("--signal-id <id>", "Acceptance signal ID to match")
    .option("--next", "Resolve the next runnable required signal for the current task")
    .option("--kind <kind>", "Evidence kind: test|command")
    .option("--worker <id>", "Worker ID (default: $USER)")
    .option("--worker-agent <id>", "Worker agent ID")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .allowExcessArguments(true)
    .helpOption("-h, --help")
    .action((opts: RunOpts, cmd: Command) => {
      if (opts.kind !== undefined && opts.kind !== "test" && opts.kind !== "command") {
        console.error(`Invalid kind: ${opts.kind}. Must be one of: test, command`);
        process.exitCode = 1;
        return;
      }

      const rawArgs =
        (cmd.parent as (Command & { rawArgs?: string[] }) | undefined)?.rawArgs ?? process.argv;
      return executeRunAction(
        opts,
        "run",
        "artifact-loop run (--signal-id <id> | --next) -- <command...>",
        rawArgs,
      );
    });
}
