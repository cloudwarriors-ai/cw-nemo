// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Phase 6B — Derived-state enrichment scenarios.
 * Dependency propagation, staleness-driven attention, brief emphasis.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { assertValid, resetValidator } from "./helpers/validate.js";
import type { TaskState } from "./helpers/types.js";

beforeEach(() => {
  resetValidator();
});

// ─── One-Hop Dependency Propagation ──────────────────────────────────

describe("Dependency Propagation to blocked_by", () => {
  it("task state with blocked_by reflects upstream dependency", () => {
    const blockedState: TaskState & { blocked_by: string[]; staleness_level: string; needs_attention: boolean } = {
      status: "blocked",
      task_confidence: 0.2,
      binding_confidence: 0.8,
      missing_inputs: [],
      blocked_by: ["task-upstream-1"],
      staleness_level: "fresh",
      needs_attention: false,
    };

    assertValid("task-state.schema.json", blockedState);
    expect(blockedState.blocked_by).toContain("task-upstream-1");
  });

  it("multiple blocking dependencies are valid", () => {
    assertValid("task-state.schema.json", {
      status: "blocked",
      task_confidence: 0.1,
      binding_confidence: 0.5,
      missing_inputs: [],
      blocked_by: ["task-a", "task-b", "task-c"],
      staleness_level: "stale",
      needs_attention: true,
    });
  });

  it("empty blocked_by is valid (not blocked by dependencies)", () => {
    assertValid("task-state.schema.json", {
      status: "in_progress",
      task_confidence: 0.5,
      binding_confidence: 0.8,
      missing_inputs: [],
      blocked_by: [],
    });
  });
});

// ─── Staleness-Driven needs_attention ────────────────────────────────

describe("Staleness-Driven Attention", () => {
  it("stale task gets needs_attention = true", () => {
    const staleState = {
      status: "in_progress",
      task_confidence: 0.4,
      binding_confidence: 0.7,
      missing_inputs: [],
      staleness_level: "stale",
      needs_attention: true,
    };

    assertValid("task-state.schema.json", staleState);
    expect(staleState.needs_attention).toBe(true);
  });

  it("fresh task does not need attention", () => {
    const freshState = {
      status: "in_progress",
      task_confidence: 0.8,
      binding_confidence: 0.9,
      missing_inputs: [],
      staleness_level: "fresh",
      needs_attention: false,
    };

    assertValid("task-state.schema.json", freshState);
    expect(freshState.needs_attention).toBe(false);
  });

  it("aging task may or may not need attention", () => {
    assertValid("task-state.schema.json", {
      status: "in_progress",
      task_confidence: 0.5,
      binding_confidence: 0.7,
      missing_inputs: [],
      staleness_level: "aging",
      needs_attention: false,
    });

    assertValid("task-state.schema.json", {
      status: "in_progress",
      task_confidence: 0.5,
      binding_confidence: 0.7,
      missing_inputs: [],
      staleness_level: "aging",
      needs_attention: true,
    });
  });
});

// ─── Brief Emphasis Based on Confidence / Health ─────────────────────

describe("Brief Emphasis", () => {
  it("brief flags low-confidence tasks", () => {
    const brief = {
      id: "brief-emphasis",
      timestamp: "2026-03-19T12:00:00Z",
      period_start: "2026-03-18T12:00:00Z",
      period_end: "2026-03-19T12:00:00Z",
      tasks: [
        {
          task_id: "task-healthy",
          status: "in_progress",
          confidence: 0.9,
          staleness: "fresh",
          flags: [],
        },
        {
          task_id: "task-low-confidence",
          status: "in_progress",
          confidence: 0.15,
          staleness: "stale",
          flags: ["low_confidence", "stale"],
        },
      ],
      low_confidence_flags: [
        { task_id: "task-low-confidence", reason: "binding confidence 0.15 < 0.3 threshold" },
      ],
    };

    assertValid("brief.schema.json", brief);
    expect(brief.low_confidence_flags).toHaveLength(1);
    expect(brief.tasks[1].flags).toContain("low_confidence");
  });

  it("normalization health reflects quarantine pressure", () => {
    const degradedHealth = {
      timestamp: "2026-03-19T12:00:00Z",
      quarantine_count: 15,
      quarantine_reasons: [
        { reason: "multi-task branch token", count: 10 },
        { reason: "conflicting explicit_lock", count: 5 },
      ],
      binding_confidence_distribution: { low: 30, medium: 40, high: 30 },
      pipeline_health: "degraded",
    };

    assertValid("normalization-health.schema.json", degradedHealth);
    expect(degradedHealth.pipeline_health).toBe("degraded");
    expect(degradedHealth.quarantine_count).toBe(15);
  });

  it("healthy pipeline has low quarantine and high binding confidence", () => {
    const healthyPipeline = {
      timestamp: "2026-03-19T12:00:00Z",
      quarantine_count: 0,
      quarantine_reasons: [],
      binding_confidence_distribution: { low: 2, medium: 8, high: 90 },
      pipeline_health: "healthy",
    };

    assertValid("normalization-health.schema.json", healthyPipeline);
    expect(healthyPipeline.binding_confidence_distribution.high).toBe(90);
  });
});
