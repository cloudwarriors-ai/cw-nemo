// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createEngine } from "../engine.js";

let dataDir: string;

function writeJson(path: string, value: unknown): void {
  writeFileSync(path, JSON.stringify(value, null, 2) + "\n", "utf-8");
}

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-engine-adoption-"));
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
});

describe("engine adopt-existing flow", () => {
  it("plans and applies legacy coordination adoption into the org model", () => {
    mkdirSync(join(dataDir, "workers"), { recursive: true });
    mkdirSync(join(dataDir, "worker-agents"), { recursive: true });
    mkdirSync(join(dataDir, "projects"), { recursive: true });
    mkdirSync(join(dataDir, "tasks"), { recursive: true });
    mkdirSync(join(dataDir, "state"), { recursive: true });
    mkdirSync(join(dataDir, "brief-schedules"), { recursive: true });

    writeJson(join(dataDir, "workers", "lead-legacy.json"), {
      id: "lead-legacy",
      display_name: "Legacy Lead",
      role: "lead",
      timezone: "America/New_York",
      active: true,
      created_at: "2026-03-19T12:00:00.000Z",
      updated_at: "2026-03-19T12:00:00.000Z",
    });
    writeJson(join(dataDir, "workers", "worker-legacy.json"), {
      id: "worker-legacy",
      display_name: "Legacy Worker",
      role: "worker",
      timezone: "America/New_York",
      active: true,
      created_at: "2026-03-19T12:00:00.000Z",
      updated_at: "2026-03-19T12:00:00.000Z",
    });
    writeJson(join(dataDir, "worker-agents", "lead-agent-legacy.json"), {
      id: "lead-agent-legacy",
      worker_id: "lead-legacy",
      label: "Legacy Lead Agent",
      connector_type: "remote",
      active: true,
      created_at: "2026-03-19T12:00:00.000Z",
      updated_at: "2026-03-19T12:00:00.000Z",
    });
    writeJson(join(dataDir, "projects", "proj-legacy.json"), {
      id: "proj-legacy",
      title: "Legacy Project",
      description: "Legacy coordination",
      owner_worker_id: "lead-legacy",
      created_at: "2026-03-19T12:00:00.000Z",
      updated_at: "2026-03-19T12:00:00.000Z",
    });
    writeJson(join(dataDir, "tasks", "task-legacy.json"), {
      id: "task-legacy",
      title: "Legacy Task",
      description: "Legacy task",
      project_id: "proj-legacy",
      assignee_human_id: "worker-legacy",
      status: "not_started",
      acceptance_criteria: "done",
      acceptance_signals: [],
      depends_on: [],
      last_activity_at: "2026-03-19T12:10:00.000Z",
    });
    writeJson(join(dataDir, "state", "task-legacy.json"), {
      status: "ready_for_review",
      task_confidence: 1,
      binding_confidence: 1,
      missing_inputs: [],
    });
    writeJson(join(dataDir, "brief-schedules", "proj-legacy.json"), {
      project_id: "proj-legacy",
      owner_worker_id: "worker-legacy",
      timezone: "America/New_York",
      delivery_hour_local: 9,
      enabled: true,
      next_run_at: "2026-03-20T13:00:00.000Z",
    });

    const engine = createEngine({ dataDir });
    const plan = engine.planAdoptExisting({
      organization: {
        id: "org-legacy",
        name: "Legacy Org",
        timezone: "America/New_York",
      },
      default_team: {
        id: "team-legacy",
        name: "Legacy Team",
        description: "Adopted legacy team",
      },
    });
    expect(plan.ready).toBe(true);
    expect(plan.membership_plans.map((membership) => membership.member_id)).toEqual([
      "lead-legacy",
      "worker-legacy",
    ]);
    expect(plan.schedule_actions).toEqual([
      {
        project_id: "proj-legacy",
        action: "disable",
        reason: "Schedule owner is not a lead/admin candidate: worker-legacy",
      },
    ]);

    const result = engine.applyAdoptExisting({
      organization: {
        id: "org-legacy",
        name: "Legacy Org",
        timezone: "America/New_York",
      },
      default_team: {
        id: "team-legacy",
        name: "Legacy Team",
        description: "Adopted legacy team",
      },
    });
    expect(result.applied).toBe(true);
    expect(engine.getOrganization()?.id).toBe("org-legacy");
    expect(engine.getProject("proj-legacy")?.team_id).toBe("team-legacy");
    expect(engine.getProjectBriefSchedule("proj-legacy")?.enabled).toBe(false);

    const summary = engine.getTeamSummary("team-legacy", "lead-legacy");
    expect(summary.total_projects).toBe(1);
    expect(summary.project_counts.ready_for_review).toBe(1);
    const brief = engine.getTeamBrief("team-legacy", "lead-legacy");
    expect(brief.project_rollup[0]?.project_id).toBe("proj-legacy");

    const status = engine.getAdoptionStatus();
    expect(status.has_report).toBe(true);
    expect(status.report?.report_id).toBe(result.report_id);
  });
});
