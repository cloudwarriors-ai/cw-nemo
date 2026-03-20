// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { resolve } from "node:path";
import { createUsageStore } from "../../usage-store.js";

export function recordTaskUseEvent(
  dataDir: string,
  action: "set" | "change" | "clear",
  taskId?: string,
  previousTaskId?: string,
): void {
  createUsageStore(resolve(dataDir)).append({
    kind: "task_use",
    timestamp: new Date().toISOString(),
    action,
    task_id: taskId,
    previous_task_id: previousTaskId,
  });
}

export function recordCommandResolution(
  dataDir: string,
  commandName: string,
  taskId: string,
  contextSource: "explicit_lock" | "session_default",
  overrideSession: boolean,
): void {
  createUsageStore(resolve(dataDir)).append({
    kind: "command_resolution",
    timestamp: new Date().toISOString(),
    command_name: commandName,
    task_id: taskId,
    context_source: contextSource,
    override_session: overrideSession,
  });
}
