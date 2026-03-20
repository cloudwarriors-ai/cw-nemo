// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveArtifactLoopClient } from "../helpers/client.js";
import { formatJson, formatTaskMessages } from "../helpers/format.js";

export function registerTaskCoordination(taskCmd: Command): void {
  taskCmd
    .command("assign <task-id>")
    .requiredOption("--worker <id>", "Assignee worker id")
    .option("--agent <id>", "Assignee agent id")
    .option("--by <id>", "Assigning worker id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (taskId: string, opts: {
      worker: string;
      agent?: string;
      by?: string;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const assignment = await client.createTaskAssignment(taskId, {
          assignee_human_id: opts.worker,
          assignee_agent_id: opts.agent,
          assigned_by: opts.by,
        });
        console.log(opts.json ? formatJson(assignment) : `Assigned ${taskId} to ${opts.worker}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  taskCmd
    .command("ping <task-id>")
    .requiredOption("--from-worker <id>", "Sender worker id")
    .option("--from-agent <id>", "Sender agent id")
    .requiredOption("--to-worker <id>", "Recipient worker id")
    .option("--to-agent <id>", "Recipient agent id")
    .requiredOption("--body <text>", "Message body")
    .option("--kind <kind>", "Message kind", "ping")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (taskId: string, opts: {
      fromWorker: string;
      fromAgent?: string;
      toWorker: string;
      toAgent?: string;
      body: string;
      kind?: "ping" | "reply" | "note";
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const message = await client.createTaskMessage(taskId, {
          sender_worker_id: opts.fromWorker,
          sender_agent_id: opts.fromAgent,
          recipient_worker_id: opts.toWorker,
          recipient_agent_id: opts.toAgent,
          kind: opts.kind ?? "ping",
          body: opts.body,
        });
        console.log(opts.json ? formatJson(message) : `Sent ${message.kind} for ${taskId}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  taskCmd
    .command("messages <task-id>")
    .option("--worker <id>", "Filter to messages involving this worker id")
    .option("--agent <id>", "Filter to messages involving this agent id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (taskId: string, opts: {
      worker?: string;
      agent?: string;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const messages = (await client.getTaskMessages(taskId)).filter((message) => {
          const workerMatch = opts.worker
            ? message.sender_worker_id === opts.worker || message.recipient_worker_id === opts.worker
            : true;
          const agentMatch = opts.agent
            ? message.sender_agent_id === opts.agent || message.recipient_agent_id === opts.agent
            : true;
          return workerMatch && agentMatch;
        });
        console.log(opts.json ? formatJson(messages) : formatTaskMessages(messages));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  taskCmd
    .command("message-ack <message-id>")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (messageId: string, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const message = await client.acknowledgeMessage(messageId);
        console.log(opts.json ? formatJson(message) : `Acknowledged message ${message.id}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
