// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from "vitest";
import {
  createOrgLoopHarness,
  expectHarnessScenario,
  type OrgLoopHarness,
} from "./org-loop-harness.js";

const smokeDescribe = process.env.ARTIFACT_LOOP_RUN_SMOKE_HARNESS === "1" ? describe : describe.skip;

const LEAD = {
  workerId: "lead-1",
  displayName: "Lead",
  role: "lead",
  timezone: "America/New_York",
  agentId: "lead-agent-1",
  agentLabel: "Lead Agent",
  connectorType: "lead-cli",
} as const;

const WORKER = {
  workerId: "worker-1",
  displayName: "Worker",
  role: "worker",
  timezone: "America/New_York",
  agentId: "worker-agent-1",
  agentLabel: "Worker Agent",
  connectorType: "remote",
} as const;

let harness: OrgLoopHarness | undefined;

afterEach(async () => {
  if (harness) {
    await harness.cleanup();
  }
  harness = undefined;
});

smokeDescribe("org-loop smoke harness", () => {
  it("drives the lead and worker loop through the built binary and shared service", async () => {
    harness = await createOrgLoopHarness({ mode: "subprocess" });
    const activeHarness = harness;
    await activeHarness.registerLead(LEAD);
    await activeHarness.addWorker(WORKER);

    await expectHarnessScenario(activeHarness, "subprocess smoke", {
      projectId: "proj-smoke",
      agentId: WORKER.agentId,
    }, async () => {
      await activeHarness.lead.createProject({
        id: "proj-smoke",
        teamId: "team-core",
        title: "Smoke Project",
        description: "Real binary smoke test",
        ownerWorkerId: LEAD.workerId,
        goal: "Exercise the real service and CLI boundary",
        scope: ["lead flow", "worker flow"],
        deliverables: ["Verified loop"],
        constraints: ["Deterministic test"],
        definitionOfDone: "Lead and worker can coordinate through the shared hub",
      });

      const draftSet = await activeHarness.lead.generateDrafts("proj-smoke");
      const approval = await activeHarness.lead.approveDrafts("proj-smoke", draftSet.id);
      const taskId = approval.tasks[0]!.id;

      await activeHarness.lead.assignTask(taskId, WORKER.workerId, WORKER.agentId);
      const inboxItem = activeHarness.getLatestInboxItem(WORKER.agentId);
      expect(inboxItem?.kind).toBe("assignment");

      const inbox = await activeHarness.workers.get(WORKER.workerId)!.readInbox();
      expect(inbox[0]?.id).toBe(inboxItem?.id);
      await activeHarness.workers.get(WORKER.workerId)!.ackInbox(inboxItem!.id);

      await activeHarness.workers.get(WORKER.workerId)!.runNext(taskId, ["node", "-e", "process.exit(0)"]);
      expect(activeHarness.getTaskState(taskId)?.status).toBe("ready_for_review");

      const message = await activeHarness.lead.pingTask({
        taskId,
        fromWorkerId: LEAD.workerId,
        fromAgentId: LEAD.agentId,
        toWorkerId: WORKER.workerId,
        toAgentId: WORKER.agentId,
        body: "Please confirm progress",
      });
      const messages = await activeHarness.workers.get(WORKER.workerId)!.readMessages(taskId);
      expect(messages.map((entry) => entry.id)).toContain(message.id);
      await activeHarness.workers.get(WORKER.workerId)!.ackMessage(message.id);

      await activeHarness.lead.scheduleBrief("proj-smoke");
      const schedule = activeHarness.engine.getProjectBriefSchedule("proj-smoke")!;
      const briefRun = await activeHarness.lead.runScheduledBriefs();
      if (briefRun.generated_count === 0) {
        activeHarness.engine.runScheduledBriefs(new Date(schedule.next_run_at!));
      }

      const latestBrief = activeHarness.getLatestBriefRun("proj-smoke");
      expect(latestBrief?.brief.by_worker.map((group) => group.worker_id)).toContain(WORKER.workerId);
      expect(latestBrief?.brief.ready_for_review.map((task) => task.id)).toContain(taskId);
    });
  });
});
