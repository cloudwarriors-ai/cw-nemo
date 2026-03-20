// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import type { CanonicalStatus } from "../../types.js";
import { resolveArtifactLoopClient } from "../helpers/client.js";
import { generateTaskDraftSetRequest } from "../helpers/draft-generation.js";
import {
  formatJson,
  formatProject,
  formatProjectBriefSchedule,
  formatProjectSummary,
  formatProjects,
  formatProjectTasks,
  formatProjectWorkerSummary,
  formatTaskDraftSet,
  formatTaskDraftSets,
} from "../helpers/format.js";

function collectValues(value: string, previous: string[] = []): string[] {
  return [...previous, value];
}

export function registerProjectCommands(program: Command): void {
  const projectCmd = program.command("project").description("Lead-facing project coordination commands");

  projectCmd
    .command("list")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const projects = await client.getProjects();
        console.log(opts.json ? formatJson(projects) : formatProjects(projects));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("show <project-id>")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const project = await client.getProject(projectId);
        if (!project) {
          throw new Error(`Project not found: ${projectId}`);
        }
        console.log(opts.json ? formatJson(project) : formatProject(project));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("tasks <project-id>")
    .option("--status <status>", "Filter by task status")
    .option("--worker <id>", "Filter by assignee worker id")
    .option("--agent <id>", "Filter by assignee agent id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, opts: {
      status?: string;
      worker?: string;
      agent?: string;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const tasks = await client.getProjectTasks(projectId, {
          status: opts.status as CanonicalStatus | undefined,
          assignee_human_id: opts.worker,
          assignee_agent_id: opts.agent,
        });
        console.log(opts.json ? formatJson(tasks) : formatProjectTasks(tasks));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("summary <project-id>")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const summary = await client.getProjectSummary(projectId);
        console.log(opts.json ? formatJson(summary) : formatProjectSummary(summary));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("workers <project-id>")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const summary = await client.getProjectWorkerSummary(projectId);
        console.log(opts.json ? formatJson(summary) : formatProjectWorkerSummary(summary));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("create")
    .requiredOption("--id <id>", "Project id")
    .requiredOption("--team <id>", "Team id")
    .requiredOption("--title <title>", "Project title")
    .requiredOption("--description <description>", "Project description")
    .requiredOption("--owner-worker <id>", "Owner worker id")
    .requiredOption("--goal <text>", "Project goal")
    .option("--scope <item>", "Scope item", collectValues, [])
    .option("--deliverable <item>", "Deliverable item", collectValues, [])
    .option("--constraint <item>", "Constraint item", collectValues, [])
    .requiredOption("--definition-of-done <text>", "Definition of done")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: {
      id: string;
      team: string;
      title: string;
      description: string;
      ownerWorker: string;
      goal: string;
      scope: string[];
      deliverable: string[];
      constraint: string[];
      definitionOfDone: string;
      json?: boolean;
      serviceUrl?: string;
      dataDir?: string;
    }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const project = await client.createProject({
          id: opts.id,
          team_id: opts.team,
          title: opts.title,
          description: opts.description,
          owner_worker_id: opts.ownerWorker,
          definition: {
            goal: opts.goal,
            scope: opts.scope,
            deliverables: opts.deliverable,
            constraints: opts.constraint,
            definition_of_done: opts.definitionOfDone,
          },
        });
        console.log(opts.json ? formatJson(project) : `Created project ${project.id}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("generate-drafts <project-id>")
    .requiredOption("--agent <id>", "Lead agent id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, opts: { agent: string; json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const project = await client.getProject(projectId);
        if (!project) {
          throw new Error(`Project not found: ${projectId}`);
        }
        const request = generateTaskDraftSetRequest(project, opts.agent);
        const draftSet = await client.createTaskDraftSet(projectId, request);
        console.log(opts.json ? formatJson(draftSet) : `Generated draft set ${draftSet.id} for ${projectId}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("draft-sets <project-id> [draft-set-id]")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, draftSetId: string | undefined, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const result = draftSetId
          ? await client.getTaskDraftSet(projectId, draftSetId)
          : await client.getTaskDraftSets(projectId);
        if (opts.json) {
          console.log(formatJson(result));
        } else if (Array.isArray(result)) {
          console.log(formatTaskDraftSets(result));
        } else if (result) {
          console.log(formatTaskDraftSet(result));
        } else {
          console.log(`Draft set not found: ${draftSetId}`);
        }
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("approve-drafts <project-id> <draft-set-id>")
    .requiredOption("--by <worker-id>", "Approving worker id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, draftSetId: string, opts: { by: string; json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const result = await client.approveTaskDraftSet(projectId, draftSetId, {
          approved_by_worker_id: opts.by,
        });
        console.log(opts.json ? formatJson(result) : `Approved draft set ${draftSetId} and created ${result.tasks.length} task(s)`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("reject-drafts <project-id> <draft-set-id>")
    .requiredOption("--by <worker-id>", "Rejecting worker id")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, draftSetId: string, opts: { by: string; json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const result = await client.rejectTaskDraftSet(projectId, draftSetId, {
          rejected_by_worker_id: opts.by,
        });
        console.log(opts.json ? formatJson(result) : `Rejected draft set ${draftSetId}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("brief <project-id>")
    .option("--latest-run", "Read the latest scheduled brief run")
    .option("--history", "Read brief run history")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, opts: { latestRun?: boolean; history?: boolean; json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const result = opts.history
          ? await client.getProjectBriefRuns(projectId)
          : opts.latestRun
            ? await client.getLatestProjectBriefRun(projectId)
            : await client.getProjectBrief(projectId);
        console.log(
          opts.json || typeof result !== "object" || result === null || !("rendered_text" in result)
            ? formatJson(result)
            : String((result as { rendered_text: string }).rendered_text),
        );
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("brief-schedule <project-id>")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, opts: { json?: boolean; serviceUrl?: string; dataDir?: string }) => {
      const client = resolveArtifactLoopClient(opts);
      try {
        const schedule = await client.getProjectBriefSchedule(projectId);
        if (!schedule) {
          throw new Error(`Brief schedule not found: ${projectId}`);
        }
        console.log(opts.json ? formatJson(schedule) : formatProjectBriefSchedule(schedule));
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });

  projectCmd
    .command("schedule-brief <project-id>")
    .requiredOption("--owner-worker <id>", "Lead owner worker id")
    .requiredOption("--timezone <tz>", "IANA timezone")
    .requiredOption("--delivery-hour <hour>", "Local delivery hour")
    .option("--disabled", "Disable schedule")
    .option("--json", "Output as JSON")
    .option("--service-url <url>", "Artifact Loop service URL")
    .option("--data-dir <dir>", "Data directory")
    .action(async (projectId: string, opts: {
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
        const schedule = await client.upsertProjectBriefSchedule(projectId, {
          owner_worker_id: opts.ownerWorker,
          timezone: opts.timezone,
          delivery_hour_local: Number.parseInt(opts.deliveryHour, 10),
          enabled: !opts.disabled,
        });
        console.log(opts.json ? formatJson(schedule) : `Updated brief schedule for ${projectId}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
