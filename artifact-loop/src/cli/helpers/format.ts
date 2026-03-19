// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { DerivationRun, Task, TaskState } from "../../types.js";

export function formatJson(data: unknown): string {
  return JSON.stringify(data, null, 2);
}

export function formatTaskReference(taskId: string, fromSession = false): string {
  return fromSession ? `${taskId} (from session)` : taskId;
}

export function formatTaskStatus(task: Task, state: TaskState, fromSession = false): string {
  const lines: string[] = [
    `Task: ${formatTaskReference(task.id, fromSession)}`,
    `Title: ${task.title}`,
    `Status: ${state.status}`,
    `Confidence: ${(state.task_confidence * 100).toFixed(0)}%`,
    `Binding: ${(state.binding_confidence * 100).toFixed(0)}%`,
  ];

  if (state.missing_inputs.length > 0) {
    lines.push(`Missing inputs:`);
    for (const mi of state.missing_inputs) {
      const resolved = mi.resolved_at ? " (resolved)" : "";
      lines.push(`  - [${mi.type}] ${mi.source}${resolved}`);
    }
  }

  if (task.override) {
    lines.push(`Override: ${task.override.status} by ${task.override.by} — ${task.override.reason}`);
  }

  return lines.join("\n");
}

export function formatDerivationHistory(taskId: string, runs: DerivationRun[], fromSession = false): string {
  const lines: string[] = [`Task: ${formatTaskReference(taskId, fromSession)}`];

  if (runs.length === 0) {
    lines.push("No derivation history.");
    return lines.join("\n");
  }

  lines.push(
    ...runs.map((run, i) => {
      const rules = run.rules_applied.join(", ");
      const override = run.input_override_id ? ` (override: ${run.input_override_id})` : "";
      return `${i + 1}. ${run.prior_state} → ${run.output_state}  [${rules}]${override}  (${run.timestamp})`;
    }),
  );

  return lines.join("\n");
}
