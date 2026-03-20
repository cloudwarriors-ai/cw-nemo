// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveArtifactLoopClient } from "../helpers/client.js";
import {
  formatInboxItems,
  formatJson,
  formatTaskMessages,
  formatWorker,
  formatWorkerAgents,
  formatWorkers,
} from "../helpers/format.js";

export function registerWorkerCommands(program: Command): void {
  const workerCmd = program.command("worker").description("Worker and worker-agent coordination commands");

  workerCmd
    .command("list")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const workers = await client.getWorkers();
        console.log(opts.json ? formatJson(workers) : formatWorkers(workers));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  workerCmd
    .command("show <worker-id>")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (workerId: string, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const worker = await client.getWorker(workerId);
        if (!worker) {
          throw new Error(`Worker not found: ${workerId}`);
        }
        console.log(opts.json ? formatJson(worker) : formatWorker(worker));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  workerCmd
    .command("create")
    .requiredOption("--id <id>", "Worker id")
    .requiredOption("--name <name>", "Display name")
    .requiredOption("--role <role>", "Worker role")
    .requiredOption("--timezone <tz>", "IANA timezone")
    .option("--inactive", "Create inactive")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: {
      id: string;
      name: string;
      role: string;
      timezone: string;
      inactive?: boolean;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const worker = await client.createWorker({
          id: opts.id,
          display_name: opts.name,
          role: opts.role,
          timezone: opts.timezone,
          active: !opts.inactive,
        });
        console.log(opts.json ? formatJson(worker) : `Created worker ${worker.id}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  workerCmd
    .command("add-agent <worker-id>")
    .requiredOption("--id <id>", "Worker agent id")
    .requiredOption("--label <label>", "Agent label")
    .requiredOption("--connector <type>", "Connector type")
    .option("--inactive", "Create inactive")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (workerId: string, opts: {
      id: string;
      label: string;
      connector: string;
      inactive?: boolean;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const agent = await client.createWorkerAgent(workerId, {
          id: opts.id,
          label: opts.label,
          connector_type: opts.connector,
          active: !opts.inactive,
        });
        console.log(opts.json ? formatJson(agent) : `Created worker agent ${agent.id}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  workerCmd
    .command("agents <worker-id>")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (workerId: string, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const agents = await client.getWorkerAgents(workerId);
        console.log(opts.json ? formatJson(agents) : formatWorkerAgents(workerId, agents));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  workerCmd
    .command("inbox")
    .requiredOption("--agent <id>", "Worker agent id")
    .option("--status <status>", "Filter by inbox status", "pending")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: { agent: string; status?: string; json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const items = await client.getWorkerAgentInbox(opts.agent, opts.status);
        console.log(opts.json ? formatJson(items) : formatInboxItems(items));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  workerCmd
    .command("inbox-ack <inbox-item-id>")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (inboxItemId: string, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const item = await client.acknowledgeInboxItem(inboxItemId);
        console.log(opts.json ? formatJson(item) : `Acknowledged inbox item ${item.id}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  workerCmd
    .command("messages")
    .requiredOption("--task <id>", "Task id")
    .requiredOption("--agent <id>", "Worker agent id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: { task: string; agent: string; json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const messages = (await client.getTaskMessages(opts.task)).filter((message) =>
          message.sender_agent_id === opts.agent || message.recipient_agent_id === opts.agent,
        );
        console.log(opts.json ? formatJson(messages) : formatTaskMessages(messages));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
