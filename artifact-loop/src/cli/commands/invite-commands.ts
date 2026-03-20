// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveArtifactLoopClient } from "../helpers/client.js";
import { formatJson } from "../helpers/format.js";

export function registerInviteCommands(program: Command): void {
  const inviteCmd = program.command("invite").description("Invite claim commands");

  inviteCmd
    .command("claim")
    .requiredOption("--token <token>", "Claim token")
    .requiredOption("--agent-id <id>", "Initial agent id")
    .requiredOption("--agent-label <label>", "Initial agent label")
    .requiredOption("--agent-connector <type>", "Initial agent connector type")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: {
      token: string;
      agentId: string;
      agentLabel: string;
      agentConnector: string;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const result = await client.claimInvite({
          claim_token: opts.token,
          agent_id: opts.agentId,
          agent_label: opts.agentLabel,
          agent_connector_type: opts.agentConnector,
        });
        console.log(opts.json ? formatJson(result) : `Claimed invite ${result.invite.id} for ${result.member.id}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
