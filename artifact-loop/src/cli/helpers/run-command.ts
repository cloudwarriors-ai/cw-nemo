// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { spawnSync } from "node:child_process";
import { evaluateSignalStatuses } from "../../derive.js";
import type {
  CommandResultPayload,
  NormalizedArtifact,
  Task,
  TestResultPayload,
} from "../../types.js";

/** Keep last 2KB of output for artifact storage. */
function truncate(text: string, maxBytes: number = 2048): string {
  if (Buffer.byteLength(text, "utf-8") <= maxBytes) return text;
  const buf = Buffer.from(text, "utf-8");
  return buf.subarray(buf.length - maxBytes).toString("utf-8");
}

export interface RunCaptureResult {
  exitCode: number;
  payload: TestResultPayload | CommandResultPayload;
  summary: string;
}

export type RunnableSignalKind = "test" | "command";

export interface NextRunnableCandidate {
  id: string;
  category: RunnableSignalKind;
}

export type NextRunnableResolution =
  | {
      ok: true;
      signalId: string;
      kind: RunnableSignalKind;
    }
  | {
      ok: false;
      reason: "no_candidate" | "ambiguous";
      candidates: NextRunnableCandidate[];
    };

function isRunnableSignalKind(category: Task["acceptance_signals"][number]["category"]): category is RunnableSignalKind {
  return category === "test" || category === "command";
}

function isNextRunnableCandidate(
  entry: ReturnType<typeof evaluateSignalStatuses>[number],
): entry is ReturnType<typeof evaluateSignalStatuses>[number] & {
  signal: ReturnType<typeof evaluateSignalStatuses>[number]["signal"] & { category: RunnableSignalKind };
} {
  return (
    entry.signal.required &&
    entry.status === "not_yet_satisfied" &&
    isRunnableSignalKind(entry.signal.category)
  );
}

export function extractWrappedCommand(argv: string[] = process.argv): string[] {
  const dashIdx = argv.indexOf("--");
  if (dashIdx === -1) {
    throw new Error("Usage: artifact-loop run --signal-id <id> -- <command...>");
  }

  const cmdArgs = argv.slice(dashIdx + 1);
  if (cmdArgs.length === 0) {
    throw new Error("No command specified after --");
  }

  return cmdArgs;
}

export function resolveNextRunnableSignal(
  task: Pick<Task, "acceptance_signals">,
  normalizedArtifacts: NormalizedArtifact[],
): NextRunnableResolution {
  const candidates = evaluateSignalStatuses(task.acceptance_signals, normalizedArtifacts)
    .filter(isNextRunnableCandidate)
    .map(({ signal }) => ({
      id: signal.id,
      category: signal.category,
    }));

  if (candidates.length === 0) {
    return {
      ok: false,
      reason: "no_candidate",
      candidates: [],
    };
  }

  if (candidates.length > 1) {
    return {
      ok: false,
      reason: "ambiguous",
      candidates,
    };
  }

  const [candidate] = candidates;
  return {
    ok: true,
    signalId: candidate.id,
    kind: candidate.category,
  };
}

export function captureRunArtifact(
  signalId: string,
  kind: "test" | "command",
  commandArgs: string[],
): RunCaptureResult {
  const [command, ...args] = commandArgs;
  const result = spawnSync(command, args, {
    stdio: ["inherit", "pipe", "pipe"],
    encoding: "utf-8",
  });

  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);

  const exitCode = result.status ?? 1;
  if (kind === "test") {
    return {
      exitCode,
      payload: {
        type: "test_result",
        signal_id: signalId,
        passed: exitCode === 0,
        output: truncate(result.stdout ?? ""),
        error: truncate(result.stderr ?? ""),
      },
      summary: `Test run: ${commandArgs.join(" ")}`,
    };
  }

  return {
    exitCode,
    payload: {
      type: "command_result",
      signal_id: signalId,
      exit_code: exitCode,
      stdout: truncate(result.stdout ?? ""),
      stderr: truncate(result.stderr ?? ""),
    },
    summary: `Command run: ${commandArgs.join(" ")}`,
  };
}
