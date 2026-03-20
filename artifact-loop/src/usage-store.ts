// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type {
  CanonicalStatus,
  NormalizedArtifact,
  Task,
  UsageEvent,
  UsageStats,
} from "./types.js";

function usageDir(dataDir: string): string {
  return join(dataDir, "usage");
}

function usageEventsPath(dataDir: string): string {
  return join(usageDir(dataDir), "events.jsonl");
}

export class UsageStore {
  constructor(private readonly dataDir: string) {
    mkdirSync(usageDir(dataDir), { recursive: true });
  }

  append(event: UsageEvent): void {
    appendFileSync(usageEventsPath(this.dataDir), JSON.stringify(event) + "\n", "utf-8");
  }

  list(): UsageEvent[] {
    const path = usageEventsPath(this.dataDir);
    if (!existsSync(path)) return [];

    return readFileSync(path, "utf-8")
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as UsageEvent);
  }
}

function increment(map: Record<string, number>, key: string): void {
  map[key] = (map[key] ?? 0) + 1;
}

function incrementStatus(
  map: Partial<Record<CanonicalStatus, number>>,
  key: CanonicalStatus,
): void {
  map[key] = (map[key] ?? 0) + 1;
}

function isAutomaticArtifact(type: string): boolean {
  return type === "test_result" || type === "command_result" || type === "git_diff_summary";
}

export function summarizeUsage(
  events: UsageEvent[],
  tasks: Task[],
  getArtifacts: (taskId: string) => NormalizedArtifact[],
): UsageStats {
  const stats: UsageStats = {
    task_use: {
      set: 0,
      change: 0,
      clear: 0,
    },
    command_resolution: {
      explicit_lock: 0,
      session_default: 0,
      explicit_over_session_override: 0,
    },
    artifacts_by_type: {},
    override_by_resulting_status: {},
    evidence_buckets: {
      manual_only: 0,
      automatic_any: 0,
      merge_only: 0,
      none: 0,
    },
  };

  for (const event of events) {
    if (event.kind === "task_use") {
      stats.task_use[event.action] += 1;
      continue;
    }

    if (event.kind === "command_resolution") {
      stats.command_resolution[event.context_source] += 1;
      if (event.override_session) {
        stats.command_resolution.explicit_over_session_override += 1;
      }
      continue;
    }

    incrementStatus(stats.override_by_resulting_status, event.resulting_status);
  }

  for (const task of tasks) {
    const artifacts = getArtifacts(task.id);
    let hasAutomatic = false;
    let hasManual = false;
    let hasMerge = false;

    for (const artifact of artifacts) {
      const type = artifact.signal_payload.type;
      increment(stats.artifacts_by_type, type);

      if (isAutomaticArtifact(type)) {
        hasAutomatic = true;
      } else if (type === "manual_event") {
        hasManual = true;
      } else if (type === "merge_result") {
        hasMerge = true;
      }
    }

    if (hasAutomatic) {
      stats.evidence_buckets.automatic_any += 1;
    } else if (hasManual) {
      stats.evidence_buckets.manual_only += 1;
    } else if (hasMerge) {
      stats.evidence_buckets.merge_only += 1;
    } else {
      stats.evidence_buckets.none += 1;
    }
  }

  return stats;
}

export function createUsageStore(dataDir: string): UsageStore {
  return new UsageStore(dataDir);
}
