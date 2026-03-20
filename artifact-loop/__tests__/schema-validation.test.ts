// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, beforeEach } from "vitest";
import { assertValid, assertInvalid, resetValidator } from "./helpers/validate.js";

beforeEach(() => {
  resetValidator();
});

// ─── Acceptance Signal ───────────────────────────────────────────────

describe("acceptance-signal.schema.json", () => {
  const schema = "acceptance-signal.schema.json";

  it("accepts valid test signal", () => {
    assertValid(schema, {
      id: "sig-1",
      category: "test",
      required: true,
      success_condition: "all tests pass",
      pattern: "test_*.py",
    });
  });

  it("accepts valid file signal", () => {
    assertValid(schema, {
      id: "sig-2",
      category: "file",
      required: false,
      success_condition: "file exists",
      path: "src/index.ts",
    });
  });

  it("accepts valid command signal", () => {
    assertValid(schema, {
      id: "sig-3",
      category: "command",
      required: true,
      success_condition: "exit code 0",
      command: "npm test",
    });
  });

  it("accepts valid merge signal (no extra fields required)", () => {
    assertValid(schema, {
      id: "sig-4",
      category: "merge",
      required: true,
      success_condition: "merged to main",
    });
  });

  it("accepts optional weight and relevance_scope", () => {
    assertValid(schema, {
      id: "sig-5",
      category: "merge",
      required: true,
      success_condition: "merged",
      weight: 0.8,
      relevance_scope: "backend",
    });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { id: "sig-1" });
  });

  it("rejects invalid category enum", () => {
    assertInvalid(schema, {
      id: "sig-1",
      category: "invalid",
      required: true,
      success_condition: "x",
    });
  });

  it("rejects test signal without pattern", () => {
    assertInvalid(schema, {
      id: "sig-1",
      category: "test",
      required: true,
      success_condition: "pass",
    });
  });

  it("rejects file signal without path", () => {
    assertInvalid(schema, {
      id: "sig-1",
      category: "file",
      required: true,
      success_condition: "exists",
    });
  });

  it("rejects command signal without command", () => {
    assertInvalid(schema, {
      id: "sig-1",
      category: "command",
      required: true,
      success_condition: "exit 0",
    });
  });
});

// ─── Normalized Artifact ─────────────────────────────────────────────

describe("normalized-artifact.schema.json", () => {
  const schema = "normalized-artifact.schema.json";

  const validTestResult = {
    id: "na-1",
    raw_artifact_id: "raw-1",
    primary_task_id: "task-1",
    session_id: "sess-1",
    artifact_source: "cli",
    worker_id: "worker-1",
    context_source: "explicit_lock",
    timestamp: "2026-03-19T12:00:00Z",
    normalization_state: "normalized",
    binding_confidence: 0.95,
    signal_payload: {
      type: "test_result",
      signal_id: "sig-1",
      passed: true,
    },
  };

  it("accepts valid test_result artifact", () => {
    assertValid(schema, validTestResult);
  });

  it("accepts valid file_change artifact", () => {
    assertValid(schema, {
      ...validTestResult,
      id: "na-2",
      signal_payload: {
        type: "file_change",
        signal_id: "sig-2",
        path: "src/index.ts",
        change_type: "modified",
      },
    });
  });

  it("accepts valid command_result artifact", () => {
    assertValid(schema, {
      ...validTestResult,
      id: "na-3",
      signal_payload: {
        type: "command_result",
        signal_id: "sig-3",
        exit_code: 0,
        stdout: "ok",
      },
    });
  });

  it("accepts valid git_diff_summary artifact", () => {
    assertValid(schema, {
      ...validTestResult,
      id: "na-3b",
      signal_payload: {
        type: "git_diff_summary",
        mode: "working_tree",
        files: [
          {
            path: "src/index.ts",
            change_type: "modified",
          },
          {
            path: "src/new.ts",
            change_type: "created",
          },
        ],
      },
    });
  });

  it("accepts valid merge_result artifact", () => {
    assertValid(schema, {
      ...validTestResult,
      id: "na-4",
      signal_payload: {
        type: "merge_result",
        signal_id: "sig-merge",
        merge_ref: "abc123",
        target_branch: "main",
      },
    });
  });

  it("accepts valid manual_event artifact", () => {
    assertValid(schema, {
      ...validTestResult,
      id: "na-5",
      signal_payload: {
        type: "manual_event",
        event_type: "approval",
        description: "PM approved",
        by: "chad",
      },
    });
  });

  it("accepts valid runtime_event artifact", () => {
    assertValid(schema, {
      ...validTestResult,
      id: "na-6",
      signal_payload: {
        type: "runtime_event",
        event_type: "deploy",
        source: "ci",
        detail: "deployed to staging",
      },
    });
  });

  it("accepts all normalization states", () => {
    for (const state of ["observed", "bound", "quarantined", "normalized", "consumed_for_derivation"]) {
      assertValid(schema, { ...validTestResult, normalization_state: state });
    }
  });

  it("rejects missing primary_task_id", () => {
    const { primary_task_id: _, ...noTaskId } = validTestResult;
    assertInvalid(schema, noTaskId);
  });

  it("rejects invalid payload type", () => {
    assertInvalid(schema, {
      ...validTestResult,
      signal_payload: {
        type: "unknown_type",
        data: "something",
      },
    });
  });

  it("rejects invalid normalization_state", () => {
    assertInvalid(schema, {
      ...validTestResult,
      normalization_state: "invalid",
    });
  });

  it("rejects missing signal_payload", () => {
    const { signal_payload: _, ...noPayload } = validTestResult;
    assertInvalid(schema, noPayload);
  });
});

// ─── Task State ──────────────────────────────────────────────────────

describe("task-state.schema.json", () => {
  const schema = "task-state.schema.json";

  const validState = {
    status: "in_progress",
    task_confidence: 0.5,
    binding_confidence: 0.8,
    missing_inputs: [],
  };

  it("accepts valid in_progress state", () => {
    assertValid(schema, validState);
  });

  it("accepts valid needs_input state with missing inputs", () => {
    assertValid(schema, {
      status: "needs_input",
      task_confidence: 0.3,
      binding_confidence: 0.7,
      missing_inputs: [
        {
          type: "human_decision",
          source: "design review",
          detected_at: "2026-03-19T12:00:00Z",
        },
      ],
    });
  });

  it("accepts all canonical statuses", () => {
    for (const status of ["not_started", "in_progress", "needs_input", "blocked", "ready_for_review", "done"]) {
      const missingInputs =
        status === "needs_input"
          ? [{ type: "dependency", source: "upstream", detected_at: "2026-03-19T12:00:00Z" }]
          : [];
      assertValid(schema, { ...validState, status, missing_inputs: missingInputs });
    }
  });

  it("rejects needs_input with empty missing_inputs", () => {
    assertInvalid(schema, {
      status: "needs_input",
      task_confidence: 0.3,
      binding_confidence: 0.7,
      missing_inputs: [],
    });
  });

  it("rejects invalid status", () => {
    assertInvalid(schema, { ...validState, status: "invalid" });
  });

  it("rejects confidence out of range", () => {
    assertInvalid(schema, { ...validState, task_confidence: 1.5 });
    assertInvalid(schema, { ...validState, task_confidence: -0.1 });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { status: "in_progress" });
  });
});

// ─── Derivation Run ─────────────────────────────────────────────────

describe("derivation-run.schema.json", () => {
  const schema = "derivation-run.schema.json";

  const validRun = {
    id: "dr-1",
    timestamp: "2026-03-19T12:00:00Z",
    task_id: "task-1",
    input_artifact_ids: ["na-1"],
    rules_applied: ["readiness_evaluation"],
    prior_state: "not_started",
    output_state: "in_progress",
  };

  it("accepts valid derivation run", () => {
    assertValid(schema, validRun);
  });

  it("accepts run with optional override id", () => {
    assertValid(schema, { ...validRun, input_override_id: "override-1" });
  });

  it("rejects empty input_artifact_ids", () => {
    assertInvalid(schema, { ...validRun, input_artifact_ids: [] });
  });

  it("rejects empty rules_applied", () => {
    assertInvalid(schema, { ...validRun, rules_applied: [] });
  });

  it("rejects invalid prior_state", () => {
    assertInvalid(schema, { ...validRun, prior_state: "invalid" });
  });

  it("rejects invalid output_state", () => {
    assertInvalid(schema, { ...validRun, output_state: "invalid" });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { id: "dr-1", timestamp: "2026-03-19T12:00:00Z" });
  });
});

// ─── Phase 4: Supporting Domain Schemas ──────────────────────────────

// ─── Task ────────────────────────────────────────────────────────────

describe("task.schema.json", () => {
  const schema = "task.schema.json";

  const validTask = {
    id: "task-1",
    title: "Implement artifact loop",
    description: "Build the v0.5 contract system",
    assignee_human_id: "chad",
    status: "in_progress",
    acceptance_criteria: "All invariant tests pass",
    acceptance_signals: [
      {
        id: "sig-1",
        category: "test",
        required: true,
        success_condition: "tests pass",
        pattern: "invariants*",
      },
    ],
    depends_on: [],
    last_activity_at: "2026-03-19T12:00:00Z",
  };

  it("accepts valid task", () => {
    assertValid(schema, validTask);
  });

  it("accepts task with optional agent and override", () => {
    assertValid(schema, {
      ...validTask,
      project_id: "proj-core",
      assignee_agent_id: "agent-1",
      override: {
        status: "blocked",
        reason: "waiting on external API",
        by: "chad",
        timestamp: "2026-03-19T12:00:00Z",
      },
    });
  });

  it("accepts task without agent (partial-assignment)", () => {
    assertValid(schema, validTask); // no assignee_agent_id
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { id: "task-1", title: "Test" });
  });
});

describe("project.schema.json", () => {
  const schema = "project.schema.json";

  const validProject = {
    id: "proj-core",
    team_id: "team-core",
    title: "Core Project",
    description: "Lead-readable coordination surface",
    owner_worker_id: "lead-1",
    created_at: "2026-03-19T12:00:00Z",
    updated_at: "2026-03-19T12:00:00Z",
  };

  it("accepts valid project", () => {
    assertValid(schema, validProject);
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { id: "proj-core", title: "Core Project" });
  });
});

describe("project-create.schema.json", () => {
  const schema = "project-create.schema.json";

  it("accepts valid project creation", () => {
    assertValid(schema, {
      id: "proj-core",
      team_id: "team-core",
      title: "Core Project",
      description: "Lead-readable coordination surface",
      owner_worker_id: "lead-1",
    });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { id: "proj-core" });
  });
});

describe("project-task-link-create.schema.json", () => {
  const schema = "project-task-link-create.schema.json";

  it("accepts valid project task link", () => {
    assertValid(schema, { task_id: "feat-http" });
  });

  it("rejects missing task_id", () => {
    assertInvalid(schema, {});
  });
});

describe("project-brief.schema.json", () => {
  const schema = "project-brief.schema.json";

  const validBrief = {
    project: {
      id: "proj-core",
      team_id: "team-core",
      title: "Core Project",
      description: "Lead-readable coordination surface",
      owner_worker_id: "lead-1",
      created_at: "2026-03-19T12:00:00Z",
      updated_at: "2026-03-19T12:00:00Z",
    },
    generated_at: "2026-03-19T12:05:00Z",
    snapshot: {
      total_tasks: 1,
      counts_by_status: {
        not_started: 0,
        in_progress: 0,
        needs_input: 0,
        blocked: 0,
        ready_for_review: 1,
        done: 0,
      },
      last_activity_at: "2026-03-19T12:00:00Z",
    },
    recent_movement: [
      {
        task_id: "feat-http",
        task_title: "HTTP Feature",
        assignee_human_id: "chad",
        assignee_agent_id: "agent-1",
        changed_at: "2026-03-19T12:00:00Z",
        from_status: "not_started",
        to_status: "ready_for_review",
        rules_applied: ["required_signals_satisfied"],
      },
    ],
    blocked: [],
    needs_input: [],
    ready_for_review: [
      {
        id: "feat-http",
        title: "HTTP Feature",
        status: "ready_for_review",
        assignee_human_id: "chad",
        assignee_agent_id: "agent-1",
        last_activity_at: "2026-03-19T12:00:00Z",
      },
    ],
    by_human: [
      {
        assignee_human_id: "chad",
        tasks: [
          {
            id: "feat-http",
            title: "HTTP Feature",
            status: "ready_for_review",
            assignee_human_id: "chad",
            assignee_agent_id: "agent-1",
            last_activity_at: "2026-03-19T12:00:00Z",
          },
        ],
      },
    ],
    by_agent: [
      {
        assignee_agent_id: "agent-1",
        tasks: [
          {
            id: "feat-http",
            title: "HTTP Feature",
            status: "ready_for_review",
            assignee_human_id: "chad",
            assignee_agent_id: "agent-1",
            last_activity_at: "2026-03-19T12:00:00Z",
          },
        ],
      },
    ],
    by_worker: [
      {
        worker_id: "worker-1",
        tasks: [
          {
            id: "feat-http",
            title: "HTTP Feature",
            status: "ready_for_review",
            assignee_human_id: "chad",
            assignee_agent_id: "agent-1",
            last_activity_at: "2026-03-19T12:00:00Z",
          },
        ],
        recent_activity_at: "2026-03-19T12:00:00Z",
        artifact_count: 1,
      },
    ],
    lead_attention_items: [
      {
        kind: "ready_for_review",
        task: {
          id: "feat-http",
          title: "HTTP Feature",
          status: "ready_for_review",
          assignee_human_id: "chad",
          assignee_agent_id: "agent-1",
          last_activity_at: "2026-03-19T12:00:00Z",
        },
        reason: "Task is ready for review.",
      },
    ],
    rendered_text: "Project Brief: Core Project (proj-core)",
  };

  it("accepts valid project brief", () => {
    assertValid(schema, validBrief);
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { project: validBrief.project });
  });
});

// ─── Task Create ─────────────────────────────────────────────────────

describe("task-create.schema.json", () => {
  const schema = "task-create.schema.json";

  const validCreate = {
    id: "task-1",
    title: "New task",
    description: "A new task",
    assignee_human_id: "chad",
    status: "not_started",
    acceptance_criteria: "It works",
    acceptance_signals: [
      {
        id: "sig-1",
        category: "test",
        required: true,
        success_condition: "pass",
        pattern: "test_*",
      },
    ],
    depends_on: [],
  };

  it("accepts valid task creation", () => {
    assertValid(schema, validCreate);
  });

  it("rejects status=done (terminal)", () => {
    assertInvalid(schema, { ...validCreate, status: "done" });
  });

  it("rejects empty acceptance_signals", () => {
    assertInvalid(schema, { ...validCreate, acceptance_signals: [] });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { id: "task-1" });
  });
});

// ─── Task Session ────────────────────────────────────────────────────

describe("task-session.schema.json", () => {
  const schema = "task-session.schema.json";

  const validSession = {
    id: "sess-1",
    task_id: "task-1",
    worker_id: "agent-1",
    start_time: "2026-03-19T10:00:00Z",
    artifact_ids: ["na-1", "na-2"],
    context_source: "explicit_lock",
  };

  it("accepts valid session", () => {
    assertValid(schema, validSession);
  });

  it("accepts session with session_default context source", () => {
    assertValid(schema, { ...validSession, context_source: "session_default" });
  });

  it("accepts session with end_time", () => {
    assertValid(schema, { ...validSession, end_time: "2026-03-19T12:00:00Z" });
  });

  it("accepts session with empty artifact_ids (active session)", () => {
    assertValid(schema, { ...validSession, artifact_ids: [] });
  });

  it("rejects invalid context_source", () => {
    assertInvalid(schema, { ...validSession, context_source: "invalid" });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { id: "sess-1" });
  });
});

// ─── Artifact (Raw) ─────────────────────────────────────────────────

describe("artifact.schema.json", () => {
  const schema = "artifact.schema.json";

  const validArtifact = {
    id: "art-1",
    type: "test_output",
    timestamp: "2026-03-19T12:00:00Z",
    source: "vitest",
    pointer: "artifact-loop/__tests__/invariants.test.ts",
    summary: "9 invariant tests passed",
  };

  it("accepts valid raw artifact", () => {
    assertValid(schema, validArtifact);
  });

  it("accepts artifact with raw_payload", () => {
    assertValid(schema, { ...validArtifact, raw_payload: { exitCode: 0, stdout: "ok" } });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { id: "art-1" });
  });
});

// ─── Override ────────────────────────────────────────────────────────

describe("override.schema.json", () => {
  const schema = "override.schema.json";

  const validOverride = {
    status: "blocked",
    reason: "Waiting on external dependency",
    by: "chad",
    timestamp: "2026-03-19T12:00:00Z",
  };

  it("accepts valid override", () => {
    assertValid(schema, validOverride);
  });

  it("accepts all canonical statuses", () => {
    for (const status of ["not_started", "in_progress", "needs_input", "blocked", "ready_for_review", "done"]) {
      assertValid(schema, { ...validOverride, status });
    }
  });

  it("rejects invalid status", () => {
    assertInvalid(schema, { ...validOverride, status: "invalid" });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { status: "blocked" });
  });
});

// ─── Missing Input ───────────────────────────────────────────────────

describe("missing-input.schema.json", () => {
  const schema = "missing-input.schema.json";

  const validMissing = {
    type: "dependency",
    source: "upstream-service",
    detected_at: "2026-03-19T12:00:00Z",
  };

  it("accepts valid missing input", () => {
    assertValid(schema, validMissing);
  });

  it("accepts resolved missing input", () => {
    assertValid(schema, {
      ...validMissing,
      resolved_at: "2026-03-19T13:00:00Z",
      resolution_artifact_id: "na-5",
    });
  });

  it("rejects invalid type", () => {
    assertInvalid(schema, { ...validMissing, type: "invalid" });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { type: "dependency" });
  });
});

// ─── Phase 5: Reporting Schemas ──────────────────────────────────────

// ─── Expanded Task State ─────────────────────────────────────────────

describe("task-state.schema.json (Phase 5 expansion)", () => {
  const schema = "task-state.schema.json";

  it("accepts task state with reporting fields", () => {
    assertValid(schema, {
      status: "blocked",
      task_confidence: 0.3,
      binding_confidence: 0.7,
      missing_inputs: [],
      blocked_by: ["task-2", "task-3"],
      staleness_level: "aging",
      needs_attention: true,
    });
  });

  it("accepts task state without reporting fields (backward compat)", () => {
    assertValid(schema, {
      status: "in_progress",
      task_confidence: 0.5,
      binding_confidence: 0.8,
      missing_inputs: [],
    });
  });

  it("rejects invalid staleness_level", () => {
    assertInvalid(schema, {
      status: "in_progress",
      task_confidence: 0.5,
      binding_confidence: 0.8,
      missing_inputs: [],
      staleness_level: "invalid",
    });
  });
});

// ─── Brief ───────────────────────────────────────────────────────────

describe("brief.schema.json", () => {
  const schema = "brief.schema.json";

  const validBrief = {
    id: "brief-1",
    timestamp: "2026-03-19T12:00:00Z",
    period_start: "2026-03-18T12:00:00Z",
    period_end: "2026-03-19T12:00:00Z",
    tasks: [
      {
        task_id: "task-1",
        status: "in_progress",
        confidence: 0.7,
        staleness: "fresh",
        flags: [],
      },
      {
        task_id: "task-2",
        status: "blocked",
        confidence: 0.2,
        staleness: "stale",
        flags: ["required_signal_failure"],
      },
    ],
  };

  it("accepts valid brief", () => {
    assertValid(schema, validBrief);
  });

  it("accepts brief with low_confidence_flags", () => {
    assertValid(schema, {
      ...validBrief,
      low_confidence_flags: [
        { task_id: "task-2", reason: "binding confidence below 0.3" },
      ],
    });
  });

  it("accepts brief with empty tasks", () => {
    assertValid(schema, { ...validBrief, tasks: [] });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { id: "brief-1" });
  });

  it("rejects task summary with missing fields", () => {
    assertInvalid(schema, {
      ...validBrief,
      tasks: [{ task_id: "task-1" }],
    });
  });
});

// ─── Assignment ──────────────────────────────────────────────────────

describe("assignment.schema.json", () => {
  const schema = "assignment.schema.json";

  const validAssignment = {
    id: "assign-1",
    task_id: "task-1",
    assignee_human_id: "chad",
    assigned_at: "2026-03-19T12:00:00Z",
  };

  it("accepts valid assignment", () => {
    assertValid(schema, validAssignment);
  });

  it("accepts assignment with optional fields", () => {
    assertValid(schema, {
      ...validAssignment,
      assignee_agent_id: "agent-1",
      assigned_by: "system",
    });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { id: "assign-1" });
  });
});

// ─── Normalization Health ────────────────────────────────────────────

describe("normalization-health.schema.json", () => {
  const schema = "normalization-health.schema.json";

  const validHealth = {
    timestamp: "2026-03-19T12:00:00Z",
    quarantine_count: 3,
    quarantine_reasons: [
      { reason: "multi-task branch token", count: 2 },
      { reason: "conflicting lock", count: 1 },
    ],
    binding_confidence_distribution: { low: 5, medium: 20, high: 75 },
    pipeline_health: "healthy",
  };

  it("accepts valid health report", () => {
    assertValid(schema, validHealth);
  });

  it("accepts degraded pipeline", () => {
    assertValid(schema, { ...validHealth, pipeline_health: "degraded" });
  });

  it("accepts unhealthy pipeline", () => {
    assertValid(schema, { ...validHealth, pipeline_health: "unhealthy" });
  });

  it("rejects invalid pipeline_health", () => {
    assertInvalid(schema, { ...validHealth, pipeline_health: "broken" });
  });

  it("rejects missing required fields", () => {
    assertInvalid(schema, { timestamp: "2026-03-19T12:00:00Z" });
  });

  it("rejects negative quarantine_count", () => {
    assertInvalid(schema, { ...validHealth, quarantine_count: -1 });
  });
});
