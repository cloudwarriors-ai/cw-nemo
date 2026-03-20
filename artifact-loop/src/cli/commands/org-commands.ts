// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveEngine } from "../helpers/engine-factory.js";
import { resolveArtifactLoopClient } from "../helpers/client.js";
import {
  formatAdoptionPlan,
  formatAdoptionStatus,
  formatJson,
  formatOrganization,
} from "../helpers/format.js";

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

  orgCmd
    .command("adopt-existing")
    .requiredOption("--org-id <id>", "Organization id")
    .requiredOption("--org-name <name>", "Organization name")
    .requiredOption("--org-timezone <tz>", "Organization timezone")
    .requiredOption("--team-id <id>", "Default team id")
    .requiredOption("--team-name <name>", "Default team name")
    .requiredOption("--team-description <text>", "Default team description")
    .option("--apply", "Apply the adoption plan")
    .option("--json", "Output as JSON")
    .option("--data-dir <dir>", "Data directory")
    .action((opts: {
      orgId: string;
      orgName: string;
      orgTimezone: string;
      teamId: string;
      teamName: string;
      teamDescription: string;
      apply?: boolean;
      json?: boolean;
      dataDir?: string;
    }) => {
      try {
        const engine = resolveEngine(opts);
        const input = {
          organization: {
            id: opts.orgId,
            name: opts.orgName,
            timezone: opts.orgTimezone,
          },
          default_team: {
            id: opts.teamId,
            name: opts.teamName,
            description: opts.teamDescription,
          },
        };
        const result = opts.apply
          ? engine.applyAdoptExisting(input)
          : engine.planAdoptExisting(input);
        if (opts.json) {
          console.log(formatJson(result));
        } else if ("applied" in result) {
          console.log(`Applied adoption report ${result.report_id}`);
          console.log(formatAdoptionStatus({ has_report: true, report: result }));
        } else {
          console.log(formatAdoptionPlan(result));
        }
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  orgCmd
    .command("adoption-status")
    .option("--json", "Output as JSON")
    .option("--data-dir <dir>", "Data directory")
    .action((opts: { json?: boolean; dataDir?: string }) => {
      try {
        const engine = resolveEngine(opts);
        const status = engine.getAdoptionStatus();
        console.log(opts.json ? formatJson(status) : formatAdoptionStatus(status));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
