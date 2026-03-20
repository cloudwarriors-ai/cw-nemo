// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AddressInfo } from "node:net";
import type { Server } from "node:http";
import { createArtifactLoopServer } from "../service/server.js";
import { createEngine } from "../engine.js";

let dataDir: string;
let server: Server | undefined;
let baseUrl = "";

async function request(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${baseUrl}${path}`, init);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init);
  return response.json() as Promise<T>;
}

beforeEach(async () => {
  dataDir = mkdtempSync(join(tmpdir(), "al-service-org-"));
  server = createArtifactLoopServer({ dataDir });
  await new Promise<void>((resolveListen) => {
    server!.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address() as AddressInfo;
  baseUrl = `http://127.0.0.1:${address.port}`;
});

afterEach(async () => {
  if (server) {
    await new Promise<void>((resolveClose, rejectClose) => {
      server!.close((err) => (err ? rejectClose(err) : resolveClose()));
    });
  }
  server = undefined;
  rmSync(dataDir, { recursive: true, force: true });
});

describe("artifact-loop organization HTTP service", () => {
  it("bootstraps org state, exposes team surfaces, and rejects duplicate bootstrap", async () => {
    const bootstrap = await request("/org/bootstrap", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        organization: {
          id: "org-core",
          name: "Core Org",
          timezone: "America/New_York",
        },
        initial_team: {
          id: "team-core",
          name: "Core Team",
          description: "Organization loop team",
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
      }),
    });
    expect(bootstrap.status).toBe(201);

    const duplicateBootstrap = await request("/org/bootstrap", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        organization: {
          id: "org-other",
          name: "Other Org",
          timezone: "America/New_York",
        },
        initial_team: {
          id: "team-other",
          name: "Other Team",
          description: "Duplicate bootstrap",
        },
        initial_member: {
          id: "lead-2",
          display_name: "Lead Two",
          timezone: "America/New_York",
        },
        initial_agent: {
          id: "lead-agent-2",
          label: "Lead Agent Two",
          connector_type: "lead-cli",
        },
      }),
    });
    expect(duplicateBootstrap.status).toBe(409);
    expect(await duplicateBootstrap.json()).toEqual({ error: "Organization already exists" });

    const org = await requestJson<{ id: string; name: string }>("/org");
    expect(org).toEqual(expect.objectContaining({ id: "org-core", name: "Core Org" }));

    const createTeam = await request("/teams", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "team-ops",
        name: "Ops",
        description: "Operations team",
        created_by_worker_id: "lead-1",
      }),
    });
    expect(createTeam.status).toBe(201);

    const teams = await requestJson<Array<{ id: string }>>("/teams");
    expect(teams.map((team) => team.id)).toEqual(["team-core", "team-ops"]);

    const team = await requestJson<{ id: string; organization_id: string }>("/teams/team-ops");
    expect(team).toEqual(expect.objectContaining({ id: "team-ops", organization_id: "org-core" }));

    const addMember = await request("/teams/team-ops/members", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        member_id: "worker-ops-1",
        role: "worker",
        display_name: "Ops Worker",
        timezone: "America/New_York",
        added_by_worker_id: "lead-1",
      }),
    });
    expect(addMember.status).toBe(201);

    const members = await requestJson<Array<{ member_id: string; role: string }>>("/teams/team-ops/members");
    expect(members.map((membership) => ({
      member_id: membership.member_id,
      role: membership.role,
    }))).toEqual([
      { member_id: "worker-ops-1", role: "worker" },
    ]);
  });

  it("supports the end-to-end organization loop over HTTP plus the local brief runner", async () => {
    await request("/org/bootstrap", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        organization: {
          id: "org-core",
          name: "Core Org",
          timezone: "America/New_York",
        },
        initial_team: {
          id: "team-core",
          name: "Core Team",
          description: "Organization loop team",
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
      }),
    });
    await request("/teams/team-core/members", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        member_id: "worker-1",
        role: "worker",
        display_name: "Worker",
        timezone: "America/New_York",
        added_by_worker_id: "lead-1",
      }),
    });
    await request("/workers/worker-1/agents", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "worker-agent-1",
        label: "Worker Agent",
        connector_type: "remote",
      }),
    });

    const project = await requestJson<{ id: string }>("/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "proj-core",
        team_id: "team-core",
        title: "Core Project",
        description: "Organization loop",
        owner_worker_id: "lead-1",
        definition: {
          goal: "Ship the organization loop",
          scope: ["lead flow", "worker flow"],
          deliverables: ["Lead workflow"],
          constraints: ["No auth"],
          definition_of_done: "Lead can assign and monitor work",
        },
      }),
    });
    expect(project.id).toBe("proj-core");

    const draftSet = await requestJson<{ id: string; drafts: Array<{ id: string }> }>(
      "/projects/proj-core/task-draft-sets/generate",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
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
        }),
      },
    );
    expect(draftSet.drafts[0]?.id).toBe("proj-core-lead-workflow");

    const approval = await requestJson<{ tasks: Array<{ id: string }> }>(
      `/projects/proj-core/task-draft-sets/${draftSet.id}/approve`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ approved_by_worker_id: "lead-1" }),
      },
    );
    expect(approval.tasks.map((task) => task.id)).toEqual(["proj-core-lead-workflow"]);

    await request("/tasks/proj-core-lead-workflow/assignments", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        assignee_human_id: "worker-1",
        assignee_agent_id: "worker-agent-1",
        assigned_by: "lead-1",
      }),
    });

    const inbox = await requestJson<Array<{ kind: string }>>("/worker-agents/worker-agent-1/inbox");
    expect(inbox[0]?.kind).toBe("assignment");

    const message = await requestJson<{ id: string }>("/tasks/proj-core-lead-workflow/messages", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        sender_worker_id: "lead-1",
        sender_agent_id: "lead-agent-1",
        recipient_worker_id: "worker-1",
        recipient_agent_id: "worker-agent-1",
        kind: "ping",
        body: "Please start this task.",
      }),
    });
    const messages = await requestJson<Array<{ id: string; kind: string }>>("/tasks/proj-core-lead-workflow/messages");
    expect(messages.map((entry) => entry.id)).toContain(message.id);

    await request(`/projects/proj-core/brief-schedule`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        owner_worker_id: "lead-1",
        timezone: "America/New_York",
        delivery_hour_local: 9,
        enabled: true,
      }),
    });

    const engine = createEngine({ dataDir });
    const schedule = engine.getProjectBriefSchedule("proj-core");
    const runResult = engine.runScheduledBriefs(new Date(schedule!.next_run_at!));
    expect(runResult.generated_count).toBe(1);

    const latestBrief = await requestJson<{ project_id: string; brief: { project: { id: string } } }>(
      "/projects/proj-core/brief-runs/latest",
    );
    expect(latestBrief.project_id).toBe("proj-core");
    expect(latestBrief.brief.project.id).toBe("proj-core");
  });

  it("supports invite claim plus team summary and brief surfaces over HTTP", async () => {
    await request("/org/bootstrap", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        organization: {
          id: "org-core",
          name: "Core Org",
          timezone: "America/New_York",
        },
        initial_team: {
          id: "team-core",
          name: "Core Team",
          description: "Organization loop team",
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
      }),
    });

    const invite = await requestJson<{ invite: { id: string; status: string }; claim_token: string }>(
      "/teams/team-core/invites",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          member_id: "worker-claim",
          role: "worker",
          display_name: "Claim Worker",
          timezone: "America/New_York",
          invited_by_worker_id: "lead-1",
        }),
      },
    );
    expect(invite.invite.status).toBe("pending");
    expect(invite.claim_token).toContain("invite-");

    const claimed = await requestJson<{ membership: { status: string }; agent: { id: string } }>(
      "/invites/claim",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          claim_token: invite.claim_token,
          agent_id: "worker-claim-agent",
          agent_label: "Claim Agent",
          agent_connector_type: "remote",
        }),
      },
    );
    expect(claimed.membership.status).toBe("active");
    expect(claimed.agent.id).toBe("worker-claim-agent");

    const summary = await requestJson<{ team: { id: string }; active_members_by_role: { worker: number } }>(
      "/teams/team-core/summary?requested_by_worker_id=lead-1",
    );
    expect(summary.team.id).toBe("team-core");
    expect(summary.active_members_by_role.worker).toBe(1);

    const brief = await requestJson<{ team: { id: string }; rendered_text: string }>(
      "/teams/team-core/brief?requested_by_worker_id=lead-1",
    );
    expect(brief.team.id).toBe("team-core");
    expect(brief.rendered_text).toContain("Team Brief: Core Team");
  });
});
