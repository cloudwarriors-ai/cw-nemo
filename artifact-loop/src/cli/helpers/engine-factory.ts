// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { resolve } from "node:path";
import { createEngine, type ArtifactLoopEngine } from "../../engine.js";

/**
 * Resolve --data-dir option or default to .artifact-loop/ in CWD.
 */
export function resolveEngine(opts: { dataDir?: string }): ArtifactLoopEngine {
  const dataDir = resolve(opts.dataDir ?? ".artifact-loop");
  return createEngine({ dataDir });
}
