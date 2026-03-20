// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveArtifactLoopClient } from "../helpers/client.js";
import { formatJson, formatOrganization } from "../helpers/format.js";

export function registerOrgCommands(program: Command): void {
  const orgCmd = program.command("org").description("Organization bootstrap and inspection commands");

  orgCmd
    .command("bootstrap")
    .requiredOption("--org-id <id>", "Organization id")
    .requiredOption("--org-name <name>", "Organization name")
    .requiredOption("--org-timezone <tz>", "Organization timezone")
    .requiredOption("--team-id <id>", "Initial team id")
    .requiredOption("--team-name <name>", "Initial team name")
    .requiredOption("--team-description <text>", "Initial team description")
    .requiredOption("--member-id <id>", "Initial member id")
    .requiredOption("--member-name <name>", "Initial member display name")
    .requiredOption("--member-timezone <tz>", "Initial member timezone")
    .requiredOption("--agent-id <id>", "Initial agent id")
    .requiredOption("--agent-label <label>", "Initial agent label")
    .requiredOption("--agent-connector <type>", "Initial agent connector type")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: {
      orgId: string;
      orgName: string;
      orgTimezone: string;
      teamId: string;
      teamName: string;
      teamDescription: string;
      memberId: string;
      memberName: string;
      memberTimezone: string;
      agentId: string;
      agentLabel: string;
      agentConnector: string;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const result = await client.bootstrapOrganization({
          organization: {
            id: opts.orgId,
            name: opts.orgName,
            timezone: opts.orgTimezone,
          },
          initial_team: {
            id: opts.teamId,
            name: opts.teamName,
            description: opts.teamDescription,
          },
          initial_member: {
            id: opts.memberId,
            display_name: opts.memberName,
            timezone: opts.memberTimezone,
          },
          initial_agent: {
            id: opts.agentId,
            label: opts.agentLabel,
            connector_type: opts.agentConnector,
          },
        });
        console.log(opts.json ? formatJson(result) : `Bootstrapped organization ${result.organization.id}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  orgCmd
    .command("show")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const organization = await client.getOrganization();
        if (!organization) {
          throw new Error("Organization not bootstrapped");
        }
        console.log(opts.json ? formatJson(organization) : formatOrganization(organization));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
