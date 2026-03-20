#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

REVIEW_ROOT="${ARTIFACT_LOOP_LEAD_REVIEW_ROOT:-$(mktemp -d /tmp/artifact-loop-lead-review-XXXXXX)}"
RUNTIME_ROOT="$REVIEW_ROOT/runtime"
MANIFEST_PATH="$REVIEW_ROOT/scenario-manifest.json"
REPORT_PATH="$REVIEW_ROOT/review-summary.md"

cleanup() {
  local keep_review="${ARTIFACT_LOOP_LEAD_REVIEW_KEEP:-1}"
  if [[ -f "$MANIFEST_PATH" ]]; then
    node --input-type=module -e '
      import { existsSync, readFileSync } from "node:fs";
      const manifestPath = process.argv[1];
      if (!existsSync(manifestPath)) process.exit(0);
      const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
      if (!manifest.keep_alive || !manifest.service_pid) process.exit(0);
      try {
        process.kill(manifest.service_pid, "SIGTERM");
      } catch {}
    ' "$MANIFEST_PATH" >/dev/null 2>&1 || true
  fi
  if [[ "$keep_review" != "1" ]]; then
    rm -rf "$REVIEW_ROOT"
  fi
}
trap cleanup EXIT

die() {
  echo "ERROR: $*" >&2
  exit 1
}

log() {
  echo "==> $*"
}

json_field() {
  local file="$1"
  local expr="$2"
  node --input-type=module -e '
    import { readFileSync } from "node:fs";
    const [path, expression] = process.argv.slice(1);
    const data = JSON.parse(readFileSync(path, "utf8"));
    const result = Function("data", `return (${expression});`)(data);
    if (result === undefined || result === null) process.exit(2);
    if (typeof result === "object") {
      console.log(JSON.stringify(result));
    } else {
      console.log(String(result));
    }
  ' "$file" "$expr" || die "Failed to read $file with expression: $expr"
}

assert_json_file() {
  local file="$1"
  local expr="$2"
  local message="$3"
  node --input-type=module -e '
    import { readFileSync } from "node:fs";
    const [path, expression, message] = process.argv.slice(1);
    const data = JSON.parse(readFileSync(path, "utf8"));
    const ok = Boolean(Function("data", `return (${expression});`)(data));
    if (!ok) {
      console.error(message);
      process.exit(1);
    }
  ' "$file" "$expr" "$message" || die "$message"
}

write_json() {
  local output_path="$1"
  shift
  "$@" >"$output_path"
}

mkdir -p "$REVIEW_ROOT"

log "Bootstrapping shared-coordination acceptance scenario"
ARTIFACT_LOOP_SCENARIO_TMPDIR="$RUNTIME_ROOT" \
ARTIFACT_LOOP_SCENARIO_MANIFEST_PATH="$MANIFEST_PATH" \
ARTIFACT_LOOP_SCENARIO_KEEP_ALIVE=1 \
bash ./scripts/scenarios/shared_coordination_v1.sh >"$REVIEW_ROOT/scenario.stdout.log"

PROJECT_ID="$(json_field "$MANIFEST_PATH" 'data.project_id')"
TASK_ID="$(json_field "$MANIFEST_PATH" 'data.task_id')"
TEAM_ID="$(json_field "$MANIFEST_PATH" 'data.team_id')"
LEAD_ID="$(json_field "$MANIFEST_PATH" 'data.lead_id')"
LEAD_AGENT_ID="$(json_field "$MANIFEST_PATH" 'data.lead_agent_id')"
WORKER_ID="$(json_field "$MANIFEST_PATH" 'data.worker_id')"
WORKER_AGENT_ID="$(json_field "$MANIFEST_PATH" 'data.worker_agent_id')"
SERVICE_URL="$(json_field "$MANIFEST_PATH" 'data.service_url')"
SERVICE_DATA_DIR="$(json_field "$MANIFEST_PATH" 'data.service_data_dir')"
MESSAGE_ID="$(json_field "$MANIFEST_PATH" 'data.message_id')"

[[ -n "$PROJECT_ID" ]] || die "project_id missing from manifest"
[[ -n "$TASK_ID" ]] || die "task_id missing from manifest"
[[ -n "$TEAM_ID" ]] || die "team_id missing from manifest"
[[ -n "$LEAD_ID" ]] || die "lead_id missing from manifest"
[[ -n "$SERVICE_URL" ]] || die "service_url missing from manifest"

log "Capturing lead-facing surfaces into $REVIEW_ROOT"
write_json "$REVIEW_ROOT/project-list.json" node bin/artifact-loop.js project list --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/project-show.json" node bin/artifact-loop.js project show "$PROJECT_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/project-tasks.json" node bin/artifact-loop.js project tasks "$PROJECT_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/project-summary.json" node bin/artifact-loop.js project summary "$PROJECT_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/project-workers.json" node bin/artifact-loop.js project workers "$PROJECT_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/project-brief-current.json" node bin/artifact-loop.js project brief "$PROJECT_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/project-brief-latest-run.json" node bin/artifact-loop.js project brief "$PROJECT_ID" --latest-run --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/project-brief-schedule.json" node bin/artifact-loop.js project brief-schedule "$PROJECT_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/task-messages.json" node bin/artifact-loop.js task messages "$TASK_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/worker-inbox.json" node bin/artifact-loop.js worker inbox --agent "$WORKER_AGENT_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/worker-show.json" node bin/artifact-loop.js worker show "$WORKER_ID" --service-url "$SERVICE_URL" --json

node bin/artifact-loop.js project summary "$PROJECT_ID" --service-url "$SERVICE_URL" >"$REVIEW_ROOT/project-summary.txt"
node bin/artifact-loop.js project workers "$PROJECT_ID" --service-url "$SERVICE_URL" >"$REVIEW_ROOT/project-workers.txt"
node bin/artifact-loop.js project brief "$PROJECT_ID" --service-url "$SERVICE_URL" >"$REVIEW_ROOT/project-brief.txt"
node bin/artifact-loop.js task messages "$TASK_ID" --service-url "$SERVICE_URL" >"$REVIEW_ROOT/task-messages.txt"

log "Creating a pending invite to validate active-member exclusion"
PENDING_INVITE_JSON="$(
  node bin/artifact-loop.js team invite "$TEAM_ID" \
    --member pending-review-worker \
    --role worker \
    --name "Pending Review Worker" \
    --timezone America/New_York \
    --by "$LEAD_ID" \
    --service-url "$SERVICE_URL" \
    --json
)"
echo "$PENDING_INVITE_JSON" >"$REVIEW_ROOT/pending-invite.json"
PENDING_INVITE_ID="$(json_field "$REVIEW_ROOT/pending-invite.json" 'data.invite.id')"

log "Scheduling and capturing team lead surfaces"
write_json "$REVIEW_ROOT/team-brief-schedule.json" node bin/artifact-loop.js team schedule-brief "$TEAM_ID" --owner-worker "$LEAD_ID" --timezone America/New_York --delivery-hour 9 --service-url "$SERVICE_URL" --json
TEAM_NEXT_RUN_AT="$(json_field "$REVIEW_ROOT/team-brief-schedule.json" 'data.next_run_at')"
[[ -n "$TEAM_NEXT_RUN_AT" ]] || die "team brief next_run_at missing"

TEAM_BRIEF_RUN_JSON="$(node bin/artifact-loop.js run-scheduled-briefs --data-dir "$SERVICE_DATA_DIR" --json)"
echo "$TEAM_BRIEF_RUN_JSON" >"$REVIEW_ROOT/team-brief-run-result.json"
TEAM_GENERATED_COUNT="$(json_field "$REVIEW_ROOT/team-brief-run-result.json" 'data.generated_team_ids.filter((id) => id === "'"$TEAM_ID"'").length')"
if [[ "$TEAM_GENERATED_COUNT" == "0" ]]; then
  log "Team brief schedule is not due yet; forcing execution at persisted next_run_at"
  node --input-type=module -e '
    import { createEngine } from "./dist/src/engine.js";
    const [dataDir, teamId, outputPath] = process.argv.slice(1);
    const engine = createEngine({ dataDir });
    const schedule = engine.getTeamBriefSchedule(teamId);
    if (!schedule?.next_run_at) {
      process.exit(1);
    }
    const result = engine.runScheduledBriefs(new Date(schedule.next_run_at));
    process.stdout.write(JSON.stringify(result, null, 2));
  ' "$SERVICE_DATA_DIR" "$TEAM_ID" >"$REVIEW_ROOT/team-brief-run-result.json"
fi

write_json "$REVIEW_ROOT/team-projects.json" node bin/artifact-loop.js team projects "$TEAM_ID" --by "$LEAD_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/team-summary.json" node bin/artifact-loop.js team summary "$TEAM_ID" --by "$LEAD_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/team-brief-current.json" node bin/artifact-loop.js team brief "$TEAM_ID" --by "$LEAD_ID" --service-url "$SERVICE_URL" --json
write_json "$REVIEW_ROOT/team-brief-latest-run.json" node bin/artifact-loop.js team brief "$TEAM_ID" --by "$LEAD_ID" --latest-run --service-url "$SERVICE_URL" --json

node bin/artifact-loop.js team summary "$TEAM_ID" --by "$LEAD_ID" --service-url "$SERVICE_URL" >"$REVIEW_ROOT/team-summary.txt"
node bin/artifact-loop.js team brief "$TEAM_ID" --by "$LEAD_ID" --service-url "$SERVICE_URL" >"$REVIEW_ROOT/team-brief.txt"

log "Checking stabilized lead-surface invariants"
assert_json_file "$REVIEW_ROOT/project-summary.json" 'data.counts_by_status.ready_for_review === 1' "Lead review expected ready_for_review=1 in project summary"
assert_json_file "$REVIEW_ROOT/project-summary.json" 'data.buckets.ready_for_review.some((task) => task.id === "'"$TASK_ID"'")' "Lead review summary missing task in ready_for_review bucket"
assert_json_file "$REVIEW_ROOT/project-workers.json" 'data.by_human.some((group) => group.assignee_human_id === "'"$WORKER_ID"'" && group.tasks.some((task) => task.id === "'"$TASK_ID"'"))' "Lead review worker summary missing human grouping"
assert_json_file "$REVIEW_ROOT/project-workers.json" 'data.by_agent.some((group) => group.assignee_agent_id === "'"$WORKER_AGENT_ID"'" && group.tasks.some((task) => task.id === "'"$TASK_ID"'"))' "Lead review worker summary missing agent grouping"
assert_json_file "$REVIEW_ROOT/project-brief-current.json" 'data.by_worker.some((group) => group.worker_id === "'"$WORKER_ID"'" && group.tasks.some((task) => task.id === "'"$TASK_ID"'"))' "Lead review current brief missing by_worker activity"
assert_json_file "$REVIEW_ROOT/project-brief-current.json" 'data.ready_for_review.some((task) => task.id === "'"$TASK_ID"'")' "Lead review current brief missing ready_for_review task"
assert_json_file "$REVIEW_ROOT/project-brief-latest-run.json" 'data.brief.by_worker.some((group) => group.worker_id === "'"$WORKER_ID"'" && group.tasks.some((task) => task.id === "'"$TASK_ID"'"))' "Lead review latest brief run missing by_worker activity"
assert_json_file "$REVIEW_ROOT/project-brief-latest-run.json" 'data.brief.recent_movement.some((item) => item.task_id === "'"$TASK_ID"'")' "Lead review latest brief run missing recent movement"
assert_json_file "$REVIEW_ROOT/project-brief-latest-run.json" 'data.brief.lead_attention_items.some((item) => item.kind === "ready_for_review" && item.task.id === "'"$TASK_ID"'")' "Lead review latest brief run missing lead attention item"
assert_json_file "$REVIEW_ROOT/task-messages.json" 'data.some((message) => message.id === "'"$MESSAGE_ID"'" && Boolean(message.acknowledged_at))' "Lead review task messages missing acknowledged ping"
assert_json_file "$REVIEW_ROOT/worker-inbox.json" 'data.every((item) => item.kind !== "assignment" || item.status !== "pending")' "Lead review expected no pending assignment inbox item after acknowledgement"
assert_json_file "$REVIEW_ROOT/pending-invite.json" 'data.invite.id === "'"$PENDING_INVITE_ID"'" && data.invite.status === "pending"' "Lead review pending invite did not stay pending"
assert_json_file "$REVIEW_ROOT/team-projects.json" 'data.length === 1 && data[0].id === "'"$PROJECT_ID"'"' "Lead review team projects did not match the reviewed project set"
assert_json_file "$REVIEW_ROOT/team-summary.json" 'data.total_projects === 1 && data.active_projects === 1' "Lead review team summary counts did not match the reviewed project set"
assert_json_file "$REVIEW_ROOT/team-summary.json" 'data.total_tasks === 1 && data.counts_by_status.ready_for_review === 1' "Lead review team summary task counts drifted from project truth"
assert_json_file "$REVIEW_ROOT/team-summary.json" 'data.member_workload.some((member) => member.member_id === "'"$WORKER_ID"'" && member.task_count === 1 && member.counts_by_status.ready_for_review === 1)' "Lead review team summary missed worker workload"
assert_json_file "$REVIEW_ROOT/team-summary.json" 'data.active_members_by_role.worker === 1' "Lead review counted pending invite-only members as active workers"
assert_json_file "$REVIEW_ROOT/team-brief-current.json" 'data.project_rollup.length === 1 && data.project_rollup[0].project_id === "'"$PROJECT_ID"'"' "Lead review team brief rollup did not prioritize the active scenario project"
assert_json_file "$REVIEW_ROOT/team-brief-current.json" 'data.lead_attention_items.some((item) => item.kind === "ready_for_review" && item.project.project_id === "'"$PROJECT_ID"'")' "Lead review team brief missed the ready_for_review attention bucket"
assert_json_file "$REVIEW_ROOT/team-brief-current.json" 'data.by_member.some((member) => member.member_id === "'"$WORKER_ID"'" && member.task_count === 1)' "Lead review team brief missed worker workload"
assert_json_file "$REVIEW_ROOT/team-brief-latest-run.json" 'data.team_id === "'"$TEAM_ID"'" && data.brief.project_rollup.some((project) => project.project_id === "'"$PROJECT_ID"'")' "Lead review latest team brief run did not persist the reviewed project"
node --input-type=module -e '
  import { createEngine } from "./dist/src/engine.js";
  const [dataDir, leadId, teamId, reviewRoot] = process.argv.slice(1);
  const engine = createEngine({ dataDir });
  const latestRun = engine.getLatestTeamBriefRun(teamId, leadId);
  if (!latestRun) {
    process.exit(1);
  }
  const inbox = engine.getInboxItems({ recipient_worker_id: leadId, statuses: ["pending"] });
  const hasTeamBriefInbox = inbox.some((item) => item.payload_ref.type === "team_brief_run" && item.payload_ref.id === latestRun.id);
  if (!hasTeamBriefInbox) {
    process.exit(2);
  }
' "$SERVICE_DATA_DIR" "$LEAD_ID" "$TEAM_ID" "$REVIEW_ROOT" || die "Lead review expected latest team brief run to be delivered to the lead inbox"

node --input-type=module -e '
  import { writeFileSync, readFileSync } from "node:fs";
  const reviewRoot = process.argv[1];
  const projectId = process.argv[2];
  const taskId = process.argv[3];
  const teamId = process.argv[4];
  const leadId = process.argv[5];
  const leadAgentId = process.argv[6];
  const workerId = process.argv[7];
  const workerAgentId = process.argv[8];
  const pendingInviteId = process.argv[9];
  const summary = JSON.parse(readFileSync(`${reviewRoot}/project-summary.json`, "utf8"));
  const brief = JSON.parse(readFileSync(`${reviewRoot}/project-brief-current.json`, "utf8"));
  const latestBrief = JSON.parse(readFileSync(`${reviewRoot}/project-brief-latest-run.json`, "utf8"));
  const messages = JSON.parse(readFileSync(`${reviewRoot}/task-messages.json`, "utf8"));
  const teamSummary = JSON.parse(readFileSync(`${reviewRoot}/team-summary.json`, "utf8"));
  const teamBrief = JSON.parse(readFileSync(`${reviewRoot}/team-brief-current.json`, "utf8"));
  const latestTeamBrief = JSON.parse(readFileSync(`${reviewRoot}/team-brief-latest-run.json`, "utf8"));
  const lines = [
    `# Lead Surface Review v1`,
    ``,
    `Project: ${projectId}`,
    `Task: ${taskId}`,
    `Team: ${teamId}`,
    `Lead: ${leadId} / ${leadAgentId}`,
    `Worker: ${workerId} / ${workerAgentId}`,
    `Pending invite: ${pendingInviteId}`,
    ``,
    `## Project Snapshot`,
    `- ready_for_review count: ${summary.counts_by_status.ready_for_review}`,
    `- current brief ready_for_review count: ${brief.ready_for_review.length}`,
    `- latest brief movement count: ${latestBrief.brief.recent_movement.length}`,
    `- task message count: ${messages.length}`,
    ``,
    `## Team Snapshot`,
    `- total projects: ${teamSummary.total_projects}`,
    `- active projects: ${teamSummary.active_projects}`,
    `- total tasks: ${teamSummary.total_tasks}`,
    `- worker active count: ${teamSummary.active_members_by_role.worker}`,
    `- current team brief rollup count: ${teamBrief.project_rollup.length}`,
    `- latest team brief movement count: ${latestTeamBrief.brief.recent_movement.length}`,
    ``,
    `## Stable Semantics Checks`,
    `- Project summary and current brief both show the task as ready_for_review.`,
    `- Project worker summary and current brief both attribute work to ${workerId}.`,
    `- Latest persisted brief run includes movement for ${taskId}.`,
    `- Lead attention stays grounded in ready_for_review state rather than message activity.`,
    `- Task messages remain acknowledged and visible without creating a second task-state path.`,
    `- Team summary totals stay aligned with the reviewed project truth rather than a second state machine.`,
    `- Team brief rollup keeps ${projectId} as the lead project and includes ${workerId} in by-member workload.`,
    `- Pending invite ${pendingInviteId} does not increase active team member counts.`,
    `- Latest persisted team brief run is delivered to the lead inbox.`,
    ``,
    `## Output Bundle`,
    `- project-summary.json / .txt`,
    `- project-workers.json / .txt`,
    `- project-brief-current.json / .txt`,
    `- project-brief-latest-run.json`,
    `- task-messages.json / .txt`,
    `- worker-inbox.json`,
    `- worker-show.json`,
    `- project-list.json`,
    `- project-show.json`,
    `- project-tasks.json`,
    `- project-brief-schedule.json`,
    `- pending-invite.json`,
    `- team-projects.json`,
    `- team-summary.json / .txt`,
    `- team-brief-current.json / .txt`,
    `- team-brief-latest-run.json`,
    `- team-brief-schedule.json`,
    `- team-brief-run-result.json`,
  ];
  writeFileSync(process.argv[10], `${lines.join("\n")}\n`, "utf8");
  console.log(lines.join("\n"));
' "$REVIEW_ROOT" "$PROJECT_ID" "$TASK_ID" "$TEAM_ID" "$LEAD_ID" "$LEAD_AGENT_ID" "$WORKER_ID" "$WORKER_AGENT_ID" "$PENDING_INVITE_ID" "$REPORT_PATH"

echo
echo "PASS lead_surface_review_v1"
echo "  review_root: $REVIEW_ROOT"
echo "  service_url: $SERVICE_URL"
echo "  project_id: $PROJECT_ID"
echo "  task_id: $TASK_ID"
echo "  report_path: $REPORT_PATH"
