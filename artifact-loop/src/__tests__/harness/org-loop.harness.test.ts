// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from "vitest";
import {
  createOrgLoopHarness,
  expectHarnessScenario,
  type OrgLoopHarness,
} from "./org-loop-harness.js";

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

const WORKER_TWO = {
  workerId: "worker-2",
  displayName: "Worker Two",
  role: "worker",
  timezone: "America/New_York",
  agentId: "worker-agent-2",
  agentLabel: "Worker Agent Two",
  connectorType: "remote",
} as const;

const PROJECT = {
  id: "proj-core",
  teamId: "team-core",
  title: "Core Project",
  description: "Harness project",
  ownerWorkerId: LEAD.workerId,
  goal: "Verify the organization loop",
  scope: ["lead flow", "worker flow"],
  deliverables: ["Lead workflow", "Worker workflow"],
  constraints: ["No frontend dependency"],
  definitionOfDone: "Lead and worker can coordinate through the hub",
} as const;

let harness: OrgLoopHarness | undefined;

afterEach(async () => {
  if (harness) {
    await harness.cleanup();
  }
  harness = undefined;
});

async function createHarness(): Promise<OrgLoopHarness> {
  harness = await createOrgLoopHarness({ mode: "in_process" });
  await harness.registerLead(LEAD);
  await harness.addWorker(WORKER);
  return harness;
}

describe("org-loop harness", () => {
  it("covers the happy path through the shared hub", async () => {
    const activeHarness = await createHarness();

    await expectHarnessScenario(activeHarness, "happy path", {
      projectId: PROJECT.id,
      agentId: WORKER.agentId,
    }, async () => {
      await activeHarness.lead.createProject(PROJECT);
      const draftSet = await activeHarness.lead.generateDrafts(PROJECT.id);
      const approval = await activeHarness.lead.approveDrafts(PROJECT.id, draftSet.id);
      const taskId = approval.tasks[0]!.id;

      await activeHarness.lead.assignTask(taskId, WORKER.workerId, WORKER.agentId);
      const inboxItem = activeHarness.getLatestInboxItem(WORKER.agentId);
      expect(inboxItem?.kind).toBe("assignment");

      const inbox = await activeHarness.workers.get(WORKER.workerId)!.readInbox();
      expect(inbox[0]?.id).toBe(inboxItem?.id);
      await activeHarness.workers.get(WORKER.workerId)!.ackInbox(inboxItem!.id);
      expect(activeHarness.getLatestInboxItem(WORKER.agentId)?.status).toBe("acknowledged");

      await activeHarness.workers.get(WORKER.workerId)!.runNext(taskId, ["node", "-e", "process.exit(0)"]);
      expect(activeHarness.getTaskState(taskId)?.status).toBe("ready_for_review");

      const message = await activeHarness.lead.pingTask({
        taskId,
        fromWorkerId: LEAD.workerId,
        fromAgentId: LEAD.agentId,
        toWorkerId: WORKER.workerId,
        toAgentId: WORKER.agentId,
        body: "Status check",
      });
      const messages = await activeHarness.workers.get(WORKER.workerId)!.readMessages(taskId);
      expect(messages.map((entry) => entry.id)).toContain(message.id);
      await activeHarness.workers.get(WORKER.workerId)!.ackMessage(message.id);
      expect(activeHarness.getLatestMessage(taskId)?.acknowledged_at).toBeTruthy();

      await activeHarness.lead.scheduleBrief(PROJECT.id);
      const schedule = activeHarness.engine.getProjectBriefSchedule(PROJECT.id);
      const result = activeHarness.engine.runScheduledBriefs(new Date(schedule!.next_run_at!));
      expect(result.generated_project_ids).toEqual([PROJECT.id]);

      const latestBrief = activeHarness.getLatestBriefRun(PROJECT.id);
      expect(latestBrief?.brief.by_worker.map((group) => group.worker_id)).toContain(WORKER.workerId);

      const summary = await activeHarness.lead.readProjectSummary(PROJECT.id);
      expect(summary.counts_by_status.ready_for_review).toBe(1);

      const workerSummary = await activeHarness.lead.readProjectWorkers(PROJECT.id);
      expect(workerSummary.by_agent[0]?.assignee_agent_id).toBe(WORKER.agentId);

      const currentBrief = await activeHarness.lead.readBrief(PROJECT.id);
      expect((currentBrief as { by_worker: Array<{ worker_id: string }> }).by_worker[0]?.worker_id).toBe(WORKER.workerId);
    });
  });

  it("supersedes the prior pending assignment inbox item on reassignment", async () => {
    const activeHarness = await createHarness();
    await activeHarness.addWorker(WORKER_TWO);

    await expectHarnessScenario(activeHarness, "reassignment", {
      projectId: PROJECT.id,
    }, async () => {
      await activeHarness.lead.createProject(PROJECT);
      const draftSet = await activeHarness.lead.generateDrafts(PROJECT.id);
      const approval = await activeHarness.lead.approveDrafts(PROJECT.id, draftSet.id);
      const taskId = approval.tasks[0]!.id;

      await activeHarness.lead.assignTask(taskId, WORKER.workerId, WORKER.agentId);
      const firstInbox = activeHarness.getLatestInboxItem(WORKER.agentId);
      expect(firstInbox?.status).toBe("pending");

      await activeHarness.lead.assignTask(taskId, WORKER_TWO.workerId, WORKER_TWO.agentId);
      const superseded = activeHarness.engine.getInboxItems({ task_id: taskId }).find((item) => item.id === firstInbox?.id);
      expect(superseded?.status).toBe("superseded");
      expect(activeHarness.getLatestInboxItem(WORKER_TWO.agentId)?.kind).toBe("reassignment");
    });
  });

  it("keeps inbox/message activity out of derivation state while preserving communication artifacts", async () => {
    const activeHarness = await createHarness();

    await expectHarnessScenario(activeHarness, "message guardrail", {
      projectId: PROJECT.id,
      agentId: WORKER.agentId,
    }, async () => {
      await activeHarness.lead.createProject(PROJECT);
      const draftSet = await activeHarness.lead.generateDrafts(PROJECT.id);
      const approval = await activeHarness.lead.approveDrafts(PROJECT.id, draftSet.id);
      const taskId = approval.tasks[0]!.id;
      await activeHarness.lead.assignTask(taskId, WORKER.workerId, WORKER.agentId);

      const before = activeHarness.getTaskState(taskId)?.status ?? "not_started";
      const message = await activeHarness.lead.pingTask({
        taskId,
        fromWorkerId: LEAD.workerId,
        fromAgentId: LEAD.agentId,
        toWorkerId: WORKER.workerId,
        toAgentId: WORKER.agentId,
        body: "No derivation from messages",
      });
      const afterPing = activeHarness.getTaskState(taskId)?.status ?? "not_started";
      expect(afterPing).toBe(before);

      await activeHarness.workers.get(WORKER.workerId)!.ackMessage(message.id);
      const afterAck = activeHarness.getTaskState(taskId)?.status ?? "not_started";
      expect(afterAck).toBe(before);

      const inbox = activeHarness.engine.getInboxItems({ task_id: taskId });
      expect(inbox.some((item) => item.kind === "message")).toBe(true);
      expect(activeHarness.getLatestMessage(taskId)?.acknowledged_at).toBeTruthy();
    });
  });

  it("scheduled brief movement reflects remote evidence and not inbox-only activity", async () => {
    const activeHarness = await createHarness();

    await expectHarnessScenario(activeHarness, "scheduled brief", {
      projectId: PROJECT.id,
      agentId: WORKER.agentId,
    }, async () => {
      await activeHarness.lead.createProject(PROJECT);
      const draftSet = await activeHarness.lead.generateDrafts(PROJECT.id);
      const approval = await activeHarness.lead.approveDrafts(PROJECT.id, draftSet.id);
      const taskId = approval.tasks[0]!.id;
      await activeHarness.lead.assignTask(taskId, WORKER.workerId, WORKER.agentId);
      await activeHarness.lead.scheduleBrief(PROJECT.id);

      const schedule = activeHarness.engine.getProjectBriefSchedule(PROJECT.id)!;
      const noEvidenceRun = activeHarness.engine.runScheduledBriefs(new Date(schedule.next_run_at!));
      expect(noEvidenceRun.generated_count).toBe(1);
      const firstBrief = activeHarness.getLatestBriefRun(PROJECT.id)!;
      expect(firstBrief.brief.recent_movement).toHaveLength(0);

      await activeHarness.workers.get(WORKER.workerId)!.runNext(taskId, ["node", "-e", "process.exit(0)"]);
      const updatedSchedule = activeHarness.engine.getProjectBriefSchedule(PROJECT.id)!;
      activeHarness.engine.runScheduledBriefs(new Date(updatedSchedule.next_run_at!));
      const secondBrief = activeHarness.getLatestBriefRun(PROJECT.id)!;
      expect(secondBrief.brief.by_worker.map((group) => group.worker_id)).toContain(WORKER.workerId);
      expect(secondBrief.brief.ready_for_review.map((task) => task.id)).toContain(taskId);
    });
  });
});
