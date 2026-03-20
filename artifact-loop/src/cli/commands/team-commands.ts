// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveArtifactLoopClient } from "../helpers/client.js";
import { formatJson, formatTeam, formatTeamMembers, formatTeams } from "../helpers/format.js";

export function registerTeamCommands(program: Command): void {
  const teamCmd = program.command("team").description("Team coordination commands");

  teamCmd
    .command("create")
    .requiredOption("--id <id>", "Team id")
    .requiredOption("--name <name>", "Team name")
    .requiredOption("--description <text>", "Team description")
    .requiredOption("--by <worker-id>", "Admin worker id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: {
      id: string;
      name: string;
      description: string;
      by: string;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const team = await client.createTeam({
          id: opts.id,
          name: opts.name,
          description: opts.description,
          created_by_worker_id: opts.by,
        });
        console.log(opts.json ? formatJson(team) : `Created team ${team.id}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("list")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const teams = await client.getTeams();
        console.log(opts.json ? formatJson(teams) : formatTeams(teams));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("show <team-id>")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (teamId: string, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const team = await client.getTeam(teamId);
        if (!team) {
          throw new Error(`Team not found: ${teamId}`);
        }
        console.log(opts.json ? formatJson(team) : formatTeam(team));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("add-member <team-id>")
    .requiredOption("--member <id>", "Member id")
    .requiredOption("--role <role>", "Team role")
    .requiredOption("--by <worker-id>", "Admin worker id")
    .option("--name <name>", "Display name when creating a new member")
    .option("--timezone <tz>", "Timezone when creating a new member")
    .option("--worker-role <role>", "Compatibility worker role field")
    .option("--inactive", "Create inactive membership")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (teamId: string, opts: {
      member: string;
      role: string;
      by: string;
      name?: string;
      timezone?: string;
      workerRole?: string;
      inactive?: boolean;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const membership = await client.addTeamMember(teamId, {
          member_id: opts.member,
          role: opts.role as "admin" | "lead" | "worker",
          status: opts.inactive ? "inactive" : "active",
          display_name: opts.name,
          timezone: opts.timezone,
          worker_role: opts.workerRole,
          added_by_worker_id: opts.by,
        });
        console.log(opts.json ? formatJson(membership) : `Added ${membership.member_id} to ${teamId} as ${membership.role}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("members <team-id>")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (teamId: string, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const memberships = await client.getTeamMembers(teamId);
        console.log(opts.json ? formatJson(memberships) : formatTeamMembers(teamId, memberships));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
