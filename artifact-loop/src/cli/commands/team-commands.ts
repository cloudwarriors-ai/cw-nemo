// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolveArtifactLoopClient } from "../helpers/client.js";
import {
  formatInvite,
  formatInviteCreateResult,
  formatInvites,
  formatJson,
  formatProjects,
  formatTeam,
  formatTeamBriefSchedule,
  formatTeamMembers,
  formatTeams,
  formatTeamSummary,
} from "../helpers/format.js";

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

  teamCmd
    .command("invite <team-id>")
    .requiredOption("--member <id>", "Reserved member id")
    .requiredOption("--role <role>", "Team role")
    .requiredOption("--name <name>", "Display name")
    .requiredOption("--timezone <tz>", "Timezone")
    .requiredOption("--by <worker-id>", "Admin worker id")
    .option("--expires-in-days <days>", "Invite expiry in days")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (teamId: string, opts: {
      member: string;
      role: string;
      name: string;
      timezone: string;
      by: string;
      expiresInDays?: string;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const invite = await client.createTeamInvite(teamId, {
          member_id: opts.member,
          role: opts.role as "admin" | "lead" | "worker",
          display_name: opts.name,
          timezone: opts.timezone,
          invited_by_worker_id: opts.by,
          expires_in_days: opts.expiresInDays ? Number.parseInt(opts.expiresInDays, 10) : undefined,
        });
        console.log(opts.json ? formatJson(invite) : formatInviteCreateResult(invite));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("invites <team-id> [invite-id]")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (teamId: string, inviteId: string | undefined, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        if (inviteId) {
          const invite = await client.getInvite(inviteId);
          if (!invite) {
            throw new Error(`Invite not found: ${inviteId}`);
          }
          console.log(opts.json ? formatJson(invite) : formatInvite(invite));
          return;
        }

        const invites = await client.getTeamInvites(teamId);
        console.log(opts.json ? formatJson(invites) : formatInvites(teamId, invites));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("revoke-invite <invite-id>")
    .requiredOption("--by <worker-id>", "Admin worker id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (inviteId: string, opts: { by: string; json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const invite = await client.revokeInvite(inviteId, {
          revoked_by_worker_id: opts.by,
        });
        console.log(opts.json ? formatJson(invite) : formatInvite(invite));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("projects <team-id>")
    .requiredOption("--by <worker-id>", "Requesting worker id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (teamId: string, opts: { by: string; json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const projects = await client.getTeamProjects(teamId, opts.by);
        console.log(opts.json ? formatJson(projects) : formatProjects(projects));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("summary <team-id>")
    .requiredOption("--by <worker-id>", "Requesting worker id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (teamId: string, opts: { by: string; json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const summary = await client.getTeamSummary(teamId, opts.by);
        console.log(opts.json ? formatJson(summary) : formatTeamSummary(summary));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("brief <team-id>")
    .requiredOption("--by <worker-id>", "Requesting worker id")
    .option("--latest-run", "Read latest scheduled team brief run")
    .option("--history", "Read team brief run history")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (teamId: string, opts: {
      by: string;
      latestRun?: boolean;
      history?: boolean;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const result = opts.history
          ? await client.getTeamBriefRuns(teamId, opts.by)
          : opts.latestRun
            ? await client.getLatestTeamBriefRun(teamId, opts.by)
            : await client.getTeamBrief(teamId, opts.by);
        const renderedText = typeof result === "object" && result !== null
          ? "rendered_text" in result
            ? String((result as { rendered_text: string }).rendered_text)
            : "brief" in result &&
                typeof (result as { brief?: unknown }).brief === "object" &&
                (result as { brief?: { rendered_text?: string } }).brief?.rendered_text
              ? String((result as { brief: { rendered_text: string } }).brief.rendered_text)
              : undefined
          : undefined;
        console.log(opts.json || !renderedText ? formatJson(result) : renderedText);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("brief-schedule <team-id>")
    .requiredOption("--by <worker-id>", "Requesting worker id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (teamId: string, opts: { by: string; json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const schedule = await client.getTeamBriefSchedule(teamId, opts.by);
        if (!schedule) {
          throw new Error(`Team brief schedule not found: ${teamId}`);
        }
        console.log(opts.json ? formatJson(schedule) : formatTeamBriefSchedule(schedule));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  teamCmd
    .command("schedule-brief <team-id>")
    .requiredOption("--owner-worker <id>", "Owner worker id")
    .requiredOption("--timezone <tz>", "IANA timezone")
    .requiredOption("--delivery-hour <hour>", "Local delivery hour")
    .option("--disabled", "Disable schedule")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (teamId: string, opts: {
      ownerWorker: string;
      timezone: string;
      deliveryHour: string;
      disabled?: boolean;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const schedule = await client.upsertTeamBriefSchedule(teamId, {
          owner_worker_id: opts.ownerWorker,
          timezone: opts.timezone,
          delivery_hour_local: Number.parseInt(opts.deliveryHour, 10),
          enabled: !opts.disabled,
        });
        console.log(opts.json ? formatJson(schedule) : formatTeamBriefSchedule(schedule));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
