// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createProgram } from "../../cli/cli.js";
import { createEngine } from "../../engine.js";

let dataDir: string;

async function runCliAsync(args: string[]): Promise<{ logs: string; errors: string }> {
  const logs: string[] = [];
  const errors: string[] = [];

  vi.spyOn(console, "log").mockImplementation((...a: unknown[]) => logs.push(String(a[0])));
  vi.spyOn(console, "error").mockImplementation((...a: unknown[]) => errors.push(String(a[0])));

  const program = createProgram();
  await program.parseAsync(["node", "test", ...args]);

  vi.restoreAllMocks();
  return {
    logs: logs.join("\n"),
    errors: errors.join("\n"),
  };
}

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "al-cli-org-"));
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
  process.exitCode = undefined;
});

describe("artifact-loop organization CLI", () => {
  it("supports the lead and worker organization loop commands locally", async () => {
    await runCliAsync([
      "org", "bootstrap",
      "--org-id", "org-core",
      "--org-name", "Core Org",
      "--org-timezone", "America/New_York",
      "--team-id", "team-core",
      "--team-name", "Core Team",
      "--team-description", "CLI org team",
      "--member-id", "lead-1",
      "--member-name", "Lead",
      "--member-timezone", "America/New_York",
      "--agent-id", "lead-agent-1",
      "--agent-label", "Lead Agent",
      "--agent-connector", "lead-cli",
      "--data-dir", dataDir,
    ]);
    await runCliAsync([
      "team", "add-member", "team-core",
      "--member", "worker-1",
      "--role", "worker",
      "--by", "lead-1",
      "--name", "Worker",
      "--timezone", "America/New_York",
      "--worker-role", "worker",
      "--data-dir", dataDir,
    ]);
    await runCliAsync([
      "worker", "add-agent", "worker-1",
      "--id", "worker-agent-1",
      "--label", "Worker Agent",
      "--connector", "remote",
      "--data-dir", dataDir,
    ]);

    await runCliAsync([
      "project", "create",
      "--id", "proj-core",
      "--team", "team-core",
      "--title", "Core Project",
      "--description", "Organization loop",
      "--owner-worker", "lead-1",
      "--goal", "Ship the organization loop",
      "--scope", "lead flow",
      "--deliverable", "Lead workflow",
      "--constraint", "No auth",
      "--definition-of-done", "Lead can define, assign, and monitor work",
      "--data-dir", dataDir,
    ]);

    const projectList = await runCliAsync([
      "project", "list",
      "--data-dir", dataDir,
    ]);
    expect(projectList.logs).toContain("proj-core: Core Project");

    const orgShow = await runCliAsync([
      "org", "show",
      "--data-dir", dataDir,
    ]);
    expect(orgShow.logs).toContain("Organization: org-core");

    const teamMembers = await runCliAsync([
      "team", "members", "team-core",
      "--data-dir", dataDir,
    ]);
    expect(teamMembers.logs).toContain("worker-1: worker (active)");

    const projectShow = await runCliAsync([
      "project", "show", "proj-core",
      "--data-dir", dataDir,
    ]);
    expect(projectShow.logs).toContain("Goal: Ship the organization loop");

    const generated = await runCliAsync([
      "project", "generate-drafts", "proj-core",
      "--agent", "lead-agent-1",
      "--data-dir", dataDir,
    ]);
    expect(generated.logs).toContain("Generated draft set");

    const engine = createEngine({ dataDir });
    const draftSet = engine.getTaskDraftSets("proj-core")[0];
    expect(draftSet?.id).toBeTruthy();

    await runCliAsync([
      "project", "approve-drafts", "proj-core", draftSet!.id,
      "--by", "lead-1",
      "--data-dir", dataDir,
    ]);
    expect(engine.getTask(draftSet!.drafts[0]!.id)).toBeTruthy();

    const projectTasks = await runCliAsync([
      "project", "tasks", "proj-core",
      "--data-dir", dataDir,
    ]);
    expect(projectTasks.logs).toContain(draftSet!.drafts[0]!.id);

    await runCliAsync([
      "task", "assign", draftSet!.drafts[0]!.id,
      "--worker", "worker-1",
      "--agent", "worker-agent-1",
      "--by", "lead-1",
      "--data-dir", dataDir,
    ]);
    const inbox = await runCliAsync([
      "worker", "inbox",
      "--agent", "worker-agent-1",
      "--data-dir", dataDir,
    ]);
    expect(inbox.logs).toContain("assignment");
    const assignmentInboxItem = engine.getWorkerAgentInbox("worker-agent-1", { status: "pending" })[0];
    expect(assignmentInboxItem?.id).toBeTruthy();

    const workerList = await runCliAsync([
      "worker", "list",
      "--data-dir", dataDir,
    ]);
    expect(workerList.logs).toContain("worker-1: Worker (worker)");

    const workerShow = await runCliAsync([
      "worker", "show", "worker-1",
      "--data-dir", dataDir,
    ]);
    expect(workerShow.logs).toContain("Timezone: America/New_York");

    const workerAgents = await runCliAsync([
      "worker", "agents", "worker-1",
      "--data-dir", dataDir,
    ]);
    expect(workerAgents.logs).toContain("worker-agent-1");

    await runCliAsync([
      "worker", "inbox-ack", assignmentInboxItem!.id,
      "--data-dir", dataDir,
    ]);
    expect(engine.getInboxItems({ recipient_agent_id: "worker-agent-1" })[0]?.status).toBe("acknowledged");

    await runCliAsync([
      "task", "ping", draftSet!.drafts[0]!.id,
      "--from-worker", "lead-1",
      "--from-agent", "lead-agent-1",
      "--to-worker", "worker-1",
      "--to-agent", "worker-agent-1",
      "--body", "Please start this task.",
      "--data-dir", dataDir,
    ]);
    const messages = await runCliAsync([
      "worker", "messages",
      "--task", draftSet!.drafts[0]!.id,
      "--agent", "worker-agent-1",
      "--data-dir", dataDir,
    ]);
    expect(messages.logs).toContain("Please start this task.");
    const taskMessages = await runCliAsync([
      "task", "messages", draftSet!.drafts[0]!.id,
      "--data-dir", dataDir,
    ]);
    expect(taskMessages.logs).toContain("Please start this task.");
    const message = engine.getTaskMessages(draftSet!.drafts[0]!.id)[0];
    await runCliAsync([
      "task", "message-ack", message!.id,
      "--data-dir", dataDir,
    ]);
    expect(engine.getTaskMessages(draftSet!.drafts[0]!.id)[0]?.acknowledged_at).toBeTruthy();

    await runCliAsync([
      "project", "schedule-brief", "proj-core",
      "--owner-worker", "lead-1",
      "--timezone", "America/New_York",
      "--delivery-hour", "9",
      "--data-dir", dataDir,
    ]);
    const schedule = engine.getProjectBriefSchedule("proj-core");
    expect(schedule?.next_run_at).toBeTruthy();
    const projectSchedule = await runCliAsync([
      "project", "brief-schedule", "proj-core",
      "--data-dir", dataDir,
    ]);
    expect(projectSchedule.logs).toContain("Delivery hour: 9");

    const projectSummary = await runCliAsync([
      "project", "summary", "proj-core",
      "--data-dir", dataDir,
    ]);
    expect(projectSummary.logs).toContain("Total tasks: 1");

    const projectWorkers = await runCliAsync([
      "project", "workers", "proj-core",
      "--data-dir", dataDir,
    ]);
    expect(projectWorkers.logs).toContain("worker-1:");

    await runCliAsync([
      "run-scheduled-briefs",
      "--data-dir", dataDir,
    ]);
  });
});
