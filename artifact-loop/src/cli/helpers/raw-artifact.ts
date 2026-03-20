// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { randomUUID } from "node:crypto";
import type { RawArtifact, SignalPayload } from "../../types.js";

/**
 * Build a RawArtifact with auto-generated id and timestamp.
 */
export function buildRawArtifact(
  type: string,
  payload: SignalPayload,
  summary: string,
  source = "cli",
): RawArtifact {
  return {
    id: randomUUID(),
    type,
    timestamp: new Date().toISOString(),
    source,
    pointer: payload.type,
    summary,
    raw_payload: payload,
  };
}
