// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Project, TaskDraft, TaskDraftSetGenerateRequest } from "../../types.js";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32) || "task";
}

export function generateTaskDraftSetRequest(project: Project, generatedByAgentId: string): TaskDraftSetGenerateRequest {
  if (!project.definition) {
    throw new Error(`Project ${project.id} does not have a definition to generate drafts from.`);
  }

  const deliverables = project.definition.deliverables.length > 0
    ? project.definition.deliverables
    : [project.definition.goal];

  const usedIds = new Set<string>();
  const drafts: TaskDraft[] = deliverables.map((deliverable, index) => {
    let baseId = `${project.id}-${slugify(deliverable)}`;
    if (usedIds.has(baseId)) {
      baseId = `${baseId}-${index + 1}`;
    }
    usedIds.add(baseId);

    return {
      id: baseId,
      title: deliverable,
      description: [
        `Project: ${project.title}`,
        `Goal: ${project.definition!.goal}`,
        `Deliverable: ${deliverable}`,
        project.definition!.scope.length > 0 ? `Scope: ${project.definition!.scope.join("; ")}` : "",
        project.definition!.constraints.length > 0 ? `Constraints: ${project.definition!.constraints.join("; ")}` : "",
      ].filter(Boolean).join("\n"),
      assignee_role_hint: "worker",
      acceptance_criteria: project.definition!.definition_of_done,
      acceptance_signals: [
        {
          id: `${baseId}-sig-complete`,
          category: "command",
          required: true,
          success_condition: project.definition!.definition_of_done,
          command: "review",
        },
      ],
      depends_on_draft_ids: [],
      rationale: `Generated from project deliverable: ${deliverable}`,
    };
  });

  return {
    generated_by_agent_id: generatedByAgentId,
    drafts,
  };
}
