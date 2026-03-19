// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { randomUUID } from "node:crypto";
import type { NormalizationContext } from "../../types.js";

/**
 * Build a NormalizationContext from CLI args.
 * --task is the explicit lock target. Worker defaults to $USER.
 */
export function buildContext(opts: { task: string; worker?: string }): NormalizationContext {
  return {
    primary_task_id: opts.task,
    session_id: `cli-${randomUUID()}`,
    worker_id: opts.worker ?? process.env.USER ?? "unknown",
    context_source: "explicit_lock",
  };
}
