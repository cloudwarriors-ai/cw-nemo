// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv, { type ErrorObject, type ValidateFunction } from "ajv";
import addFormats from "ajv-formats";

export const CONTRACT_IDS = {
  assignment: "assignment.schema.json",
  assignmentCreate: "assignment-create.schema.json",
  inboxItem: "inbox-item.schema.json",
  ingestRequest: "ingest-request.schema.json",
  normalizationContext: "normalization-context.schema.json",
  normalizedArtifact: "normalized-artifact.schema.json",
  organization: "organization.schema.json",
  organizationBootstrap: "organization-bootstrap.schema.json",
  project: "project.schema.json",
  projectBrief: "project-brief.schema.json",
  projectBriefRun: "project-brief-run.schema.json",
  projectBriefSchedule: "project-brief-schedule.schema.json",
  projectBriefScheduleUpsert: "project-brief-schedule-upsert.schema.json",
  projectCreate: "project-create.schema.json",
  projectDefinition: "project-definition.schema.json",
  projectSummary: "project-summary.schema.json",
  projectTaskLinkCreate: "project-task-link-create.schema.json",
  projectWorkerSummary: "project-worker-summary.schema.json",
  team: "team.schema.json",
  teamCreate: "team-create.schema.json",
  teamMembership: "team-membership.schema.json",
  teamMembershipCreate: "team-membership-create.schema.json",
  taskDraft: "task-draft.schema.json",
  taskDraftSet: "task-draft-set.schema.json",
  taskDraftSetApprove: "task-draft-set-approve.schema.json",
  taskDraftSetGenerate: "task-draft-set-generate.schema.json",
  taskDraftSetReject: "task-draft-set-reject.schema.json",
  taskMessage: "task-message.schema.json",
  taskMessageCreate: "task-message-create.schema.json",
  task: "task.schema.json",
  taskCreate: "task-create.schema.json",
  worker: "worker.schema.json",
  workerAgent: "worker-agent.schema.json",
  workerAgentCreate: "worker-agent-create.schema.json",
  workerCreate: "worker-create.schema.json",
} as const;

function contractsDir(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    resolve(here, "../../../contracts"),
    resolve(here, "../../contracts"),
  ];
  const match = candidates.find((candidate) => existsSync(candidate));
  if (!match) {
    throw new Error(`Contracts directory not found for ${here}`);
  }
  return match;
}

function formatErrors(errors: ErrorObject[] | null | undefined): string[] {
  return (errors ?? []).map((error) => {
    const instancePath = error.instancePath || "/";
    return `${instancePath} ${error.message ?? "is invalid"}`.trim();
  });
}

export class ContractValidator {
  private readonly ajv: Ajv;

  constructor() {
    this.ajv = new Ajv({
      allErrors: true,
      strict: false,
    });
    addFormats(this.ajv);

    for (const file of readdirSync(contractsDir()).filter((entry) => entry.endsWith(".schema.json"))) {
      const schemaPath = join(contractsDir(), file);
      const schema = JSON.parse(readFileSync(schemaPath, "utf-8")) as { $id?: string };
      this.ajv.addSchema(schema, schema.$id ?? file);
    }
  }

  validate(schemaId: string, data: unknown): string[] {
    const validate = this.ajv.getSchema(schemaId);
    if (!validate) {
      throw new Error(`Schema not loaded: ${schemaId}`);
    }

    return validate(data) ? [] : formatErrors(validate.errors);
  }

  assertValid(schemaId: string, data: unknown): void {
    const errors = this.validate(schemaId, data);
    if (errors.length > 0) {
      throw new Error(errors.join("; "));
    }
  }

  getSchema(schemaId: string): ValidateFunction | undefined {
    return this.ajv.getSchema(schemaId);
  }
}

let singleton: ContractValidator | undefined;

export function getContractValidator(): ContractValidator {
  singleton ??= new ContractValidator();
  return singleton;
}
