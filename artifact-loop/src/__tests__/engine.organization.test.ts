// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createEngine } from "../engine.js";

let dataDir: string;

function bootstrapOrg(engine: ReturnType<typeof createEngine>): void {
  engine.bootstrapOrganization({
    organization: {
      id: "org-core",
      name: "Core Org",
      timezone: "America/New_York",
    },
    initial_team: {
      id: "team-core",
      name: "Core Team",
      description: "Organization test team",
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
  });
  engine.addTeamMember("team-core", {
    member_id: "worker-1",
    role: "worker",
    display_name: "Worker",
    timezone: "America/New_York",
    worker_role: "worker",
    added_by_worker_id: "lead-1",
  });
}

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-engine-org-"));
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
});

describe("engine organization loop", () => {
  it("bootstraps a single organization only once", () => {
    const engine = createEngine({ dataDir });
    bootstrapOrg(engine);

    expect(engine.getOrganization()).toEqual(expect.objectContaining({
      id: "org-core",
      name: "Core Org",
    }));
    expect(engine.getTeams().map((team) => team.id)).toEqual(["team-core"]);
    expect(engine.getTeamMembers("team-core").map((membership) => membership.member_id)).toEqual([
      "lead-1",
      "worker-1",
    ]);

    expect(() => bootstrapOrg(engine)).toThrowError("Organization already exists");
  });

  it("enforces team-local project, assignment, message, and brief ownership boundaries", () => {
    const engine = createEngine({ dataDir });
    bootstrapOrg(engine);
    engine.createTeam({
      id: "team-other",
      name: "Other Team",
      description: "Second test team",
      created_by_worker_id: "lead-1",
    });
    engine.addTeamMember("team-other", {
      member_id: "worker-2",
      role: "worker",
      display_name: "Worker Two",
      timezone: "America/New_York",
      worker_role: "worker",
      added_by_worker_id: "lead-1",
    });
    engine.addTeamMember("team-core", {
      member_id: "worker-only",
      role: "worker",
      display_name: "Worker Only",
      timezone: "America/New_York",
      worker_role: "worker",
      added_by_worker_id: "lead-1",
    });
    engine.createWorkerAgent("worker-1", {
      id: "worker-agent-1",
      label: "Worker Agent",
      connector_type: "remote",
    });
    engine.createWorkerAgent("worker-2", {
      id: "worker-agent-2",
      label: "Other Worker Agent",
      connector_type: "remote",
    });

    expect(() => engine.createProject({
      id: "proj-invalid",
      team_id: "team-core",
      title: "Invalid Project",
      description: "Worker cannot create project",
      owner_worker_id: "worker-only",
      definition: {
        goal: "Fail",
        scope: ["test"],
        deliverables: ["none"],
        constraints: [],
        definition_of_done: "n/a",
      },
    })).toThrowError("Member lacks required team role: worker-only in team-core");

    const project = engine.createProject({
      id: "proj-core",
      team_id: "team-core",
      title: "Core Project",
      description: "Organization loop",
      owner_worker_id: "lead-1",
      definition: {
        goal: "Ship the organization loop",
        scope: ["lead flow", "worker flow"],
        deliverables: ["Lead workflow", "Worker workflow"],
        constraints: ["No auth"],
        definition_of_done: "Lead can define, assign, and monitor tasks",
      },
    });
    engine.createTask({
      id: "task-core",
      title: "Task Core",
      description: "Team scoped task",
      assignee_human_id: "worker-1",
      status: "not_started",
      acceptance_criteria: "done",
      acceptance_signals: [],
      depends_on: [],
    });
    engine.assignTaskToProject(project.id, "task-core");

    expect(() => engine.createAssignment("task-core", {
      assignee_human_id: "worker-2",
      assignee_agent_id: "worker-agent-2",
      assigned_by: "lead-1",
    })).toThrowError("Member is not active in team: worker-2 in team-core");

    expect(() => engine.createTaskMessage("task-core", {
      sender_worker_id: "lead-1",
      sender_agent_id: "lead-agent-1",
      recipient_worker_id: "worker-2",
      recipient_agent_id: "worker-agent-2",
      kind: "ping",
      body: "Cross-team ping",
    })).toThrowError("Member is not active in team: worker-2 in team-core");

    expect(() => engine.upsertProjectBriefSchedule("proj-core", {
      owner_worker_id: "worker-only",
      timezone: "America/New_York",
      delivery_hour_local: 9,
      enabled: true,
    })).toThrowError("Member lacks required team role: worker-only in team-core");
  });

  it("supports draft approval, assignment inbox, task messages, and scheduled brief runs", () => {
    const engine = createEngine({ dataDir });
    bootstrapOrg(engine);
    engine.createWorkerAgent("worker-1", {
      id: "worker-agent-1",
      label: "Worker Agent",
      connector_type: "remote",
    });

    const project = engine.createProject({
      id: "proj-core",
      team_id: "team-core",
      title: "Core Project",
      description: "Organization loop",
      owner_worker_id: "lead-1",
      definition: {
        goal: "Ship the organization loop",
        scope: ["lead flow", "worker flow"],
        deliverables: ["Lead workflow", "Worker workflow"],
        constraints: ["No auth"],
        definition_of_done: "Lead can define, assign, and monitor tasks",
      },
    });
    expect(project.owner_worker_id).toBe("lead-1");

    const draftSet = engine.createTaskDraftSet("proj-core", {
      generated_by_agent_id: "lead-agent-1",
      drafts: [
        {
          id: "proj-core-lead-workflow",
          title: "Lead workflow",
          description: "Lead-facing flow",
          assignee_role_hint: "worker",
          acceptance_criteria: "Lead flow works",
          acceptance_signals: [],
          depends_on_draft_ids: [],
          rationale: "Generated from deliverable",
        },
      ],
    });

    const approved = engine.approveTaskDraftSet("proj-core", draftSet.id, {
      approved_by_worker_id: "lead-1",
    });
    expect(approved.tasks.map((task) => task.id)).toEqual(["proj-core-lead-workflow"]);
    expect(engine.getTask("proj-core-lead-workflow")?.project_id).toBe("proj-core");

    const assignment = engine.createAssignment("proj-core-lead-workflow", {
      assignee_human_id: "worker-1",
      assignee_agent_id: "worker-agent-1",
      assigned_by: "lead-1",
    });
    const inbox = engine.getWorkerAgentInbox("worker-agent-1");
    expect(inbox[0]).toEqual(expect.objectContaining({
      kind: "assignment",
      payload_ref: { type: "assignment", id: assignment.id },
    }));

    const message = engine.createTaskMessage("proj-core-lead-workflow", {
      sender_worker_id: "lead-1",
      sender_agent_id: "lead-agent-1",
      recipient_worker_id: "worker-1",
      recipient_agent_id: "worker-agent-1",
      kind: "ping",
      body: "Please start this task.",
    });
    expect(engine.getTaskMessages("proj-core-lead-workflow").map((entry) => entry.id)).toEqual([message.id]);

    const schedule = engine.upsertProjectBriefSchedule("proj-core", {
      owner_worker_id: "lead-1",
      timezone: "America/New_York",
      delivery_hour_local: 9,
      enabled: true,
    });
    expect(schedule.next_run_at).toBeTruthy();

    const result = engine.runScheduledBriefs(new Date(schedule.next_run_at!));
    expect(result.generated_count).toBe(1);
    expect(result.generated_project_ids).toEqual(["proj-core"]);
    expect(engine.getLatestProjectBriefRun("proj-core")?.project_id).toBe("proj-core");

    const leadInbox = engine.getInboxItems({ recipient_worker_id: "lead-1", statuses: ["pending"] });
    expect(leadInbox.some((item) => item.kind === "brief")).toBe(true);
  });
});
