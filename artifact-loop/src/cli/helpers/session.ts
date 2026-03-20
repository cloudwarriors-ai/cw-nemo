// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { join, resolve } from "node:path";
import { createEngine } from "../../engine.js";

interface Session {
  current_task_id: string;
  set_at: string;
}

export interface ResolvedTaskTarget {
  taskId: string;
  fromSession: boolean;
  contextSource: "explicit_lock" | "session_default";
  overrideSession: boolean;
}

function sessionPath(dataDir: string): string {
  return join(dataDir, "session.json");
}

/** Read the current session, or undefined if none set. */
export function getSession(dataDir: string): Session | undefined {
  try {
    const raw = readFileSync(sessionPath(dataDir), "utf-8");
    return JSON.parse(raw) as Session;
  } catch {
    return undefined;
  }
}

/** Set the current task in the session file. Validates task exists. */
export function setSession(dataDir: string, taskId: string): void {
  const engine = createEngine({ dataDir });
  const task = engine.getTask(taskId);
  if (!task) {
    throw new Error(`Task not found: ${taskId}`);
  }
  const session: Session = {
    current_task_id: taskId,
    set_at: new Date().toISOString(),
  };
  writeFileSync(sessionPath(dataDir), JSON.stringify(session, null, 2) + "\n");
}

/** Clear the current session. */
export function clearSession(dataDir: string): void {
  try {
    unlinkSync(sessionPath(dataDir));
  } catch {
    // Already cleared or never set — fine
  }
}

/**
 * Resolve the task ID from explicit flag, session file, or throw.
 * Precedence: flag > session > error.
 */
export function resolveTaskId(opts: { task?: string; dataDir?: string }): string {
  return resolveTaskTarget(opts).taskId;
}

export function resolveTaskTarget(opts: { task?: string; dataDir?: string }): ResolvedTaskTarget {
  const dataDir = resolve(opts.dataDir ?? ".artifact-loop");
  const session = getSession(dataDir);

  if (opts.task) {
    return {
      taskId: opts.task,
      fromSession: false,
      contextSource: "explicit_lock",
      overrideSession: session?.current_task_id !== undefined,
    };
  }
  if (session?.current_task_id) {
    return {
      taskId: session.current_task_id,
      fromSession: true,
      contextSource: "session_default",
      overrideSession: false,
    };
  }

  throw new Error(
    'No task specified. Use --task <id> or run: artifact-loop task use <id>',
  );
}
