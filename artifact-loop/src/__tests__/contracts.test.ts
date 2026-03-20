// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import { CONTRACT_IDS, getContractValidator } from "../service/schema-validator.js";

describe("contract validation", () => {
  const validator = getContractValidator();

  it("accepts assignment-create requests", () => {
    const errors = validator.validate(CONTRACT_IDS.assignmentCreate, {
      assignee_human_id: "chad",
      assignee_agent_id: "worker-agent-1",
      assigned_by: "lead",
    });

    expect(errors).toEqual([]);
  });

  it("accepts project-create requests", () => {
    const errors = validator.validate(CONTRACT_IDS.projectCreate, {
      id: "proj-core",
      team_id: "team-core",
      title: "Core Project",
      description: "Lead-readable coordination surface",
      owner_worker_id: "lead-1",
      definition: {
        goal: "Ship the coordination loop",
        scope: ["task generation", "worker inbox"],
        deliverables: ["Lead workflow", "Worker workflow"],
        constraints: ["No dashboard", "No auth"],
        definition_of_done: "Lead can coordinate workers through the hub",
      },
    });

    expect(errors).toEqual([]);
  });

  it("accepts org bootstrap, team, membership, worker, worker agent, task draft, inbox, message, and brief schedule contracts", () => {
    expect(validator.validate(CONTRACT_IDS.organizationBootstrap, {
      organization: {
        id: "org-core",
        name: "Core Org",
        timezone: "America/New_York",
      },
      initial_team: {
        id: "team-core",
        name: "Core Team",
        description: "Core team",
      },
      initial_member: {
        id: "lead-1",
        display_name: "Lead",
        timezone: "America/New_York",
      },
      initial_agent: {
        id: "lead-agent-1",
        label: "Lead Agent",
        connector_type: "lead-cli",
      },
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.teamCreate, {
      id: "team-core",
      name: "Core Team",
      description: "Core team",
      created_by_worker_id: "lead-1",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.teamMembershipCreate, {
      member_id: "worker-1",
      role: "worker",
      display_name: "Worker One",
      timezone: "America/New_York",
      worker_role: "worker",
      added_by_worker_id: "lead-1",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.workerCreate, {
      id: "worker-1",
      display_name: "Worker One",
      role: "worker",
      timezone: "America/New_York",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.workerAgentCreate, {
      id: "agent-1",
      label: "Worker Agent",
      connector_type: "remote",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.taskDraftSetGenerate, {
      generated_by_agent_id: "lead-agent-1",
      drafts: [
        {
          id: "proj-core-deliverable-1",
          title: "Lead workflow",
          description: "Build the lead workflow",
          assignee_role_hint: "worker",
          acceptance_criteria: "Lead can create and assign tasks",
          acceptance_signals: [],
          depends_on_draft_ids: [],
          rationale: "Generated from deliverable",
        },
      ],
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.inboxItem, {
      id: "inbox-1",
      recipient_worker_id: "worker-1",
      recipient_agent_id: "agent-1",
      project_id: "proj-core",
      task_id: "task-1",
      kind: "assignment",
      status: "pending",
      created_at: "2026-03-19T12:00:00.000Z",
      payload_ref: { type: "assignment", id: "assign-1" },
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.taskMessageCreate, {
      sender_worker_id: "lead-1",
      sender_agent_id: "lead-agent-1",
      recipient_worker_id: "worker-1",
      recipient_agent_id: "agent-1",
      kind: "ping",
      body: "Please pick this up next.",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.projectBriefScheduleUpsert, {
      owner_worker_id: "lead-1",
      timezone: "America/New_York",
      delivery_hour_local: 9,
      enabled: true,
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.inviteCreate, {
      member_id: "worker-claim",
      role: "worker",
      display_name: "Claim Worker",
      timezone: "America/New_York",
      invited_by_worker_id: "lead-1",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.inviteClaim, {
      claim_token: "invite-123.token",
      agent_id: "worker-claim-agent",
      agent_label: "Claim Agent",
      agent_connector_type: "remote",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.teamBriefScheduleUpsert, {
      owner_worker_id: "lead-1",
      timezone: "America/New_York",
      delivery_hour_local: 9,
      enabled: true,
    })).toEqual([]);
  });

  it("accepts project task link requests", () => {
    const errors = validator.validate(CONTRACT_IDS.projectTaskLinkCreate, {
      task_id: "feat-http",
    });

    expect(errors).toEqual([]);
  });

  it("accepts normalization context with worker agent provenance", () => {
    const errors = validator.validate(CONTRACT_IDS.normalizationContext, {
      primary_task_id: "feat-http",
      session_id: "session-1",
      worker_id: "worker-1",
      worker_agent_id: "worker-agent-1",
      context_source: "explicit_lock",
    });

    expect(errors).toEqual([]);
  });

  it("accepts normalized artifacts with persisted provenance fields", () => {
    const errors = validator.validate(CONTRACT_IDS.normalizedArtifact, {
      id: "na-ra-test-1",
      raw_artifact_id: "ra-test-1",
      primary_task_id: "feat-http",
      session_id: "session-1",
      artifact_source: "remote_worker_connector",
      worker_id: "worker-1",
      worker_agent_id: "worker-agent-1",
      context_source: "explicit_lock",
      timestamp: "2026-03-19T12:00:00.000Z",
      normalization_state: "normalized",
      binding_confidence: 1,
      signal_payload: {
        type: "test_result",
        signal_id: "sig-test",
        passed: true,
      },
    });

    expect(errors).toEqual([]);
  });

  it("accepts project summary read models", () => {
    const errors = validator.validate(CONTRACT_IDS.projectSummary, {
      project: {
        id: "proj-core",
        team_id: "team-core",
        title: "Core Project",
        description: "Lead-readable coordination surface",
        owner_worker_id: "lead-1",
        created_at: "2026-03-19T12:00:00.000Z",
        updated_at: "2026-03-19T12:00:00.000Z",
      },
      total_tasks: 1,
      counts_by_status: {
        not_started: 0,
        in_progress: 0,
        needs_input: 0,
        blocked: 0,
        ready_for_review: 1,
        done: 0,
      },
      buckets: {
        blocked: [],
        needs_input: [],
        ready_for_review: [
          {
            id: "feat-http",
            title: "HTTP Feature",
            status: "ready_for_review",
            assignee_human_id: "chad",
            assignee_agent_id: "worker-agent-1",
            last_activity_at: "2026-03-19T12:00:00.000Z",
          },
        ],
      },
      last_activity_at: "2026-03-19T12:00:00.000Z",
    });

    expect(errors).toEqual([]);
  });

  it("accepts project brief read models", () => {
    const errors = validator.validate(CONTRACT_IDS.projectBrief, {
      project: {
        id: "proj-core",
        team_id: "team-core",
        title: "Core Project",
        description: "Lead-readable coordination surface",
        owner_worker_id: "lead-1",
        created_at: "2026-03-19T12:00:00.000Z",
        updated_at: "2026-03-19T12:00:00.000Z",
      },
      generated_at: "2026-03-19T12:05:00.000Z",
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
        last_activity_at: "2026-03-19T12:00:00.000Z",
      },
      recent_movement: [
        {
          task_id: "feat-http",
          task_title: "HTTP Feature",
          assignee_human_id: "chad",
          assignee_agent_id: "worker-agent-1",
          changed_at: "2026-03-19T12:00:00.000Z",
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
          assignee_agent_id: "worker-agent-1",
          last_activity_at: "2026-03-19T12:00:00.000Z",
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
              assignee_agent_id: "worker-agent-1",
              last_activity_at: "2026-03-19T12:00:00.000Z",
            },
          ],
          recent_activity_at: "2026-03-19T12:00:00.000Z",
          artifact_count: 1,
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
              assignee_agent_id: "worker-agent-1",
              last_activity_at: "2026-03-19T12:00:00.000Z",
            },
          ],
        },
      ],
      by_agent: [
        {
          assignee_agent_id: "worker-agent-1",
          tasks: [
            {
              id: "feat-http",
              title: "HTTP Feature",
              status: "ready_for_review",
              assignee_human_id: "chad",
              assignee_agent_id: "worker-agent-1",
              last_activity_at: "2026-03-19T12:00:00.000Z",
            },
          ],
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
            assignee_agent_id: "worker-agent-1",
            last_activity_at: "2026-03-19T12:00:00.000Z",
          },
          reason: "Task is ready for review.",
        },
      ],
      rendered_text: "Project Brief: Core Project (proj-core)",
    });

    expect(errors).toEqual([]);
  });

  it("accepts project worker summary read models", () => {
    const errors = validator.validate(CONTRACT_IDS.projectWorkerSummary, {
      project_id: "proj-core",
      by_human: [
        {
          assignee_human_id: "chad",
          tasks: [
            {
              id: "feat-http",
              title: "HTTP Feature",
              status: "ready_for_review",
              assignee_human_id: "chad",
              assignee_agent_id: "worker-agent-1",
              last_activity_at: "2026-03-19T12:00:00.000Z",
            },
          ],
        },
      ],
      by_agent: [
        {
          assignee_agent_id: "worker-agent-1",
          tasks: [
            {
              id: "feat-http",
              title: "HTTP Feature",
              status: "ready_for_review",
              assignee_human_id: "chad",
              assignee_agent_id: "worker-agent-1",
              last_activity_at: "2026-03-19T12:00:00.000Z",
            },
          ],
        },
      ],
    });

    expect(errors).toEqual([]);
  });

  it("accepts invite and team read model contracts", () => {
    expect(validator.validate(CONTRACT_IDS.invite, {
      id: "invite-1",
      team_id: "team-core",
      member_id: "worker-claim",
      role: "worker",
      display_name: "Claim Worker",
      timezone: "America/New_York",
      status: "pending",
      invited_by_worker_id: "lead-1",
      created_at: "2026-03-19T12:00:00.000Z",
      expires_at: "2026-03-26T12:00:00.000Z",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.inviteCreateResult, {
      invite: {
        id: "invite-1",
        team_id: "team-core",
        member_id: "worker-claim",
        role: "worker",
        display_name: "Claim Worker",
        timezone: "America/New_York",
        status: "pending",
        invited_by_worker_id: "lead-1",
        created_at: "2026-03-19T12:00:00.000Z",
        expires_at: "2026-03-26T12:00:00.000Z",
      },
      claim_token: "invite-1.token",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.inviteClaimResult, {
      invite: {
        id: "invite-1",
        team_id: "team-core",
        member_id: "worker-claim",
        role: "worker",
        display_name: "Claim Worker",
        timezone: "America/New_York",
        status: "claimed",
        invited_by_worker_id: "lead-1",
        created_at: "2026-03-19T12:00:00.000Z",
        expires_at: "2026-03-26T12:00:00.000Z",
        claimed_at: "2026-03-19T12:05:00.000Z",
      },
      membership: {
        member_id: "worker-claim",
        team_id: "team-core",
        role: "worker",
        status: "active",
        created_at: "2026-03-19T12:00:00.000Z",
        updated_at: "2026-03-19T12:05:00.000Z",
      },
      member: {
        id: "worker-claim",
        display_name: "Claim Worker",
        role: "worker",
        timezone: "America/New_York",
        active: true,
        created_at: "2026-03-19T12:05:00.000Z",
        updated_at: "2026-03-19T12:05:00.000Z",
      },
      agent: {
        id: "worker-claim-agent",
        worker_id: "worker-claim",
        label: "Claim Agent",
        connector_type: "remote",
        active: true,
        created_at: "2026-03-19T12:05:00.000Z",
        updated_at: "2026-03-19T12:05:00.000Z",
      },
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.teamSummary, {
      team: {
        id: "team-core",
        organization_id: "org-core",
        name: "Core Team",
        description: "Core team",
        created_at: "2026-03-19T12:00:00.000Z",
        updated_at: "2026-03-19T12:00:00.000Z",
      },
      total_projects: 1,
      active_projects: 1,
      total_tasks: 1,
      counts_by_status: {
        not_started: 0,
        in_progress: 0,
        needs_input: 0,
        blocked: 0,
        ready_for_review: 1,
        done: 0,
      },
      project_counts: {
        blocked: 0,
        needs_input: 0,
        ready_for_review: 1,
        healthy: 0,
      },
      active_members_by_role: {
        admin: 1,
        lead: 0,
        worker: 1,
      },
      member_workload: [
        {
          member_id: "worker-claim",
          role: "worker",
          project_ids: ["proj-core"],
          task_count: 1,
          counts_by_status: {
            not_started: 0,
            in_progress: 0,
            needs_input: 0,
            blocked: 0,
            ready_for_review: 1,
            done: 0,
          },
          recent_activity_at: "2026-03-19T12:05:00.000Z",
        },
      ],
      attention: {
        blocked_projects: [],
        needs_input_projects: [],
        ready_for_review_projects: [
          {
            project_id: "proj-core",
            title: "Core Project",
            total_tasks: 1,
            counts_by_status: {
              not_started: 0,
              in_progress: 0,
              needs_input: 0,
              blocked: 0,
              ready_for_review: 1,
              done: 0,
            },
            blocked_count: 0,
            needs_input_count: 0,
            ready_for_review_count: 1,
            last_activity_at: "2026-03-19T12:05:00.000Z",
          },
        ],
      },
      projects: [
        {
          project_id: "proj-core",
          title: "Core Project",
          total_tasks: 1,
          counts_by_status: {
            not_started: 0,
            in_progress: 0,
            needs_input: 0,
            blocked: 0,
            ready_for_review: 1,
            done: 0,
          },
          blocked_count: 0,
          needs_input_count: 0,
          ready_for_review_count: 1,
          last_activity_at: "2026-03-19T12:05:00.000Z",
        },
      ],
      last_activity_at: "2026-03-19T12:05:00.000Z",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.teamBrief, {
      team: {
        id: "team-core",
        organization_id: "org-core",
        name: "Core Team",
        description: "Core team",
        created_at: "2026-03-19T12:00:00.000Z",
        updated_at: "2026-03-19T12:00:00.000Z",
      },
      generated_at: "2026-03-19T12:05:00.000Z",
      snapshot: {
        total_projects: 1,
        active_projects: 1,
        total_tasks: 1,
        counts_by_status: {
          not_started: 0,
          in_progress: 0,
          needs_input: 0,
          blocked: 0,
          ready_for_review: 1,
          done: 0,
        },
        last_activity_at: "2026-03-19T12:05:00.000Z",
      },
      blocked_projects: [],
      needs_input_projects: [],
      ready_for_review_projects: [
        {
          project_id: "proj-core",
          title: "Core Project",
          total_tasks: 1,
          counts_by_status: {
            not_started: 0,
            in_progress: 0,
            needs_input: 0,
            blocked: 0,
            ready_for_review: 1,
            done: 0,
          },
          blocked_count: 0,
          needs_input_count: 0,
          ready_for_review_count: 1,
          last_activity_at: "2026-03-19T12:05:00.000Z",
        },
      ],
      project_rollup: [
        {
          project_id: "proj-core",
          title: "Core Project",
          total_tasks: 1,
          counts_by_status: {
            not_started: 0,
            in_progress: 0,
            needs_input: 0,
            blocked: 0,
            ready_for_review: 1,
            done: 0,
          },
          blocked_count: 0,
          needs_input_count: 0,
          ready_for_review_count: 1,
          last_activity_at: "2026-03-19T12:05:00.000Z",
        },
      ],
      by_member: [
        {
          member_id: "worker-claim",
          role: "worker",
          project_ids: ["proj-core"],
          task_count: 1,
          counts_by_status: {
            not_started: 0,
            in_progress: 0,
            needs_input: 0,
            blocked: 0,
            ready_for_review: 1,
            done: 0,
          },
          recent_activity_at: "2026-03-19T12:05:00.000Z",
        },
      ],
      recent_movement: [
        {
          project_id: "proj-core",
          task_id: "task-1",
          task_title: "Task 1",
          assignee_human_id: "worker-claim",
          changed_at: "2026-03-19T12:05:00.000Z",
          from_status: "not_started",
          to_status: "ready_for_review",
          rules_applied: ["override"],
        },
      ],
      lead_attention_items: [
        {
          kind: "ready_for_review",
          project: {
            project_id: "proj-core",
            title: "Core Project",
            total_tasks: 1,
            counts_by_status: {
              not_started: 0,
              in_progress: 0,
              needs_input: 0,
              blocked: 0,
              ready_for_review: 1,
              done: 0,
            },
            blocked_count: 0,
            needs_input_count: 0,
            ready_for_review_count: 1,
            last_activity_at: "2026-03-19T12:05:00.000Z",
          },
          reason: "Project has work ready for review.",
        },
      ],
      rendered_text: "Team Brief: Core Team (team-core)",
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.teamBriefSchedule, {
      team_id: "team-core",
      owner_worker_id: "lead-1",
      timezone: "America/New_York",
      delivery_hour_local: 9,
      enabled: true,
    })).toEqual([]);

    expect(validator.validate(CONTRACT_IDS.teamBriefRun, {
      id: "team-brief-run-1",
      team_id: "team-core",
      generated_at: "2026-03-19T12:05:00.000Z",
      window_start: "2026-03-19T12:00:00.000Z",
      window_end: "2026-03-19T12:05:00.000Z",
      brief: {
        team: {
          id: "team-core",
          organization_id: "org-core",
          name: "Core Team",
          description: "Core team",
          created_at: "2026-03-19T12:00:00.000Z",
          updated_at: "2026-03-19T12:00:00.000Z",
        },
        generated_at: "2026-03-19T12:05:00.000Z",
        snapshot: {
          total_projects: 1,
          active_projects: 1,
          total_tasks: 1,
          counts_by_status: {
            not_started: 0,
            in_progress: 0,
            needs_input: 0,
            blocked: 0,
            ready_for_review: 1,
            done: 0,
          },
          last_activity_at: "2026-03-19T12:05:00.000Z",
        },
        blocked_projects: [],
        needs_input_projects: [],
        ready_for_review_projects: [],
        project_rollup: [],
        by_member: [],
        recent_movement: [],
        lead_attention_items: [],
        rendered_text: "Team Brief: Core Team (team-core)",
      },
    })).toEqual([]);
  });
});
