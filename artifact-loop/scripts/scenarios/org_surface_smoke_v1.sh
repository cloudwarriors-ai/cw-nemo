#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
source "$ROOT_DIR/scripts/scenarios/lib/shared-coordination-common.sh"

TMP_ROOT="${ARTIFACT_LOOP_SCENARIO_TMPDIR:-$(mktemp -d /tmp/artifact-loop-org-surface-smoke-XXXXXX)}"
SERVICE_DATA_DIR="$TMP_ROOT/service-data"
LEAD_DATA_DIR="$TMP_ROOT/lead-data"
WORKER_DATA_DIR="$TMP_ROOT/worker-data"
LEGACY_DATA_DIR="$TMP_ROOT/legacy-data"
MANIFEST_PATH="${ARTIFACT_LOOP_SCENARIO_MANIFEST_PATH:-}"
REPORT_PATH="$TMP_ROOT/org-surface-smoke-summary.md"
KEEP_ALIVE="${ARTIFACT_LOOP_SCENARIO_KEEP_ALIVE:-0}"

resolve_service_port() {
  if [[ -n "${ARTIFACT_LOOP_SCENARIO_PORT:-}" ]]; then
    echo "$ARTIFACT_LOOP_SCENARIO_PORT"
    return
  fi
  node --input-type=module -e '
    import net from "node:net";
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        process.exit(1);
      }
      console.log(address.port);
      server.close();
    });
  '
}

SERVICE_PORT="$(resolve_service_port)"
SERVICE_URL="http://127.0.0.1:${SERVICE_PORT}"

PROJECT_ID="proj-org-surface"
ORG_ID="org-core"
TEAM_ID="team-core"
LEAD_ID="lead-1"
LEAD_AGENT_ID="lead-agent-1"
WORKER_ID="worker-claim"
WORKER_AGENT_ID="worker-claim-agent"
INVITE_ID=""
TEAM_BRIEF_RUN_ID=""
ADOPTION_REPORT_PATH=""
SERVICE_PID=""

cleanup() {
  if [[ "$KEEP_ALIVE" == "1" ]]; then
    return
  fi
  if [[ -n "${SERVICE_PID}" ]] && kill -0 "${SERVICE_PID}" >/dev/null 2>&1; then
    kill "${SERVICE_PID}" >/dev/null 2>&1 || true
    wait "${SERVICE_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

mkdir -p "$SERVICE_DATA_DIR" "$LEAD_DATA_DIR" "$WORKER_DATA_DIR" "$LEGACY_DATA_DIR"

PROJECT_TITLE="Org Surface Smoke"
PROJECT_DESCRIPTION="Mixed CLI and HTTP stabilization validation"
PROJECT_GOAL="Validate invite claim, team read models, and adoption flows"
PROJECT_DELIVERABLE="Stabilization signoff"
PROJECT_CONSTRAINT="CLI plus HTTP only"
PROJECT_DEFINITION_OF_DONE="Invite claim, team surfaces, and adoption flow all pass"

scenario_log "Building artifact-loop"
npm run build >/dev/null

scenario_log "Starting shared service on ${SERVICE_URL}"
node bin/artifact-loop.js serve \
  --host 127.0.0.1 \
  --port "${SERVICE_PORT}" \
  --data-dir "$SERVICE_DATA_DIR" \
  >"$TMP_ROOT/service.stdout.log" \
  2>"$TMP_ROOT/service.stderr.log" &
SERVICE_PID=$!

for _ in $(seq 1 100); do
  if curl -fsS "${SERVICE_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
curl -fsS "${SERVICE_URL}/health" >/dev/null || scenario_die "Service failed to become healthy"

scenario_log "Bootstrapping organization and lead"
run_cmd node bin/artifact-loop.js org bootstrap \
  --org-id "$ORG_ID" \
  --org-name "Core Org" \
  --org-timezone America/New_York \
  --team-id "$TEAM_ID" \
  --team-name "Core Team" \
  --team-description "Organization stabilization team" \
  --member-id "$LEAD_ID" \
  --member-name Lead \
  --member-timezone America/New_York \
  --agent-id "$LEAD_AGENT_ID" \
  --agent-label "Lead Agent" \
  --agent-connector lead-cli \
  --service-url "$SERVICE_URL"

scenario_log "Creating invite over CLI"
INVITE_JSON="$(run_json node bin/artifact-loop.js team invite "$TEAM_ID" \
  --member "$WORKER_ID" \
  --role worker \
  --name "Claim Worker" \
  --timezone America/New_York \
  --by "$LEAD_ID" \
  --service-url "$SERVICE_URL" \
  --json)"
INVITE_ID="$(json_field "$INVITE_JSON" 'data.invite.id')"
CLAIM_TOKEN="$(json_field "$INVITE_JSON" 'data.claim_token')"
assert_json "$INVITE_JSON" 'data.invite.status === "pending"' "Invite did not start pending"
[[ -n "$CLAIM_TOKEN" ]] || scenario_die "Claim token was empty"

scenario_log "Claiming invite over HTTP"
CLAIM_PAYLOAD="$(node --input-type=module -e '
  const [claimToken, agentId, agentLabel, agentConnector] = process.argv.slice(1);
  console.log(JSON.stringify({
    claim_token: claimToken,
    agent_id: agentId,
    agent_label: agentLabel,
    agent_connector_type: agentConnector,
  }));
' "$CLAIM_TOKEN" "$WORKER_AGENT_ID" "Claim Agent" "remote")"
CLAIM_JSON="$(http_json POST "${SERVICE_URL}/invites/claim" "$CLAIM_PAYLOAD")"
assert_json "$CLAIM_JSON" 'data.invite.id === "'"$INVITE_ID"'"' "Claim result returned the wrong invite id"
assert_json "$CLAIM_JSON" 'data.invite.status === "claimed"' "Invite claim did not mark the invite claimed"
assert_json "$CLAIM_JSON" 'data.member.id === "'"$WORKER_ID"'"' "Claim result returned the wrong member id"
assert_json "$CLAIM_JSON" 'data.agent.id === "'"$WORKER_AGENT_ID"'"' "Claim result returned the wrong agent id"

run_shared_coordination_flow

scenario_log "Reading team surfaces over HTTP"
TEAM_PROJECTS_JSON="$(http_json GET "${SERVICE_URL}/teams/${TEAM_ID}/projects?requested_by_worker_id=${LEAD_ID}")"
assert_json "$TEAM_PROJECTS_JSON" 'data.some((project) => project.id === "'"$PROJECT_ID"'")' "Team projects did not include the scenario project"

TEAM_SUMMARY_JSON="$(http_json GET "${SERVICE_URL}/teams/${TEAM_ID}/summary?requested_by_worker_id=${LEAD_ID}")"
assert_json "$TEAM_SUMMARY_JSON" 'data.total_projects === 1' "Team summary reported the wrong total_projects"
assert_json "$TEAM_SUMMARY_JSON" 'data.active_projects === 1' "Team summary reported the wrong active_projects"
assert_json "$TEAM_SUMMARY_JSON" 'data.total_tasks === 1' "Team summary reported the wrong total_tasks"
assert_json "$TEAM_SUMMARY_JSON" 'data.counts_by_status.ready_for_review === 1' "Team summary missed ready_for_review"
assert_json "$TEAM_SUMMARY_JSON" 'data.member_workload.some((member) => member.member_id === "'"$WORKER_ID"'" && member.task_count === 1)' "Team summary missed claimed worker workload"

TEAM_BRIEF_JSON="$(http_json GET "${SERVICE_URL}/teams/${TEAM_ID}/brief?requested_by_worker_id=${LEAD_ID}")"
assert_json "$TEAM_BRIEF_JSON" 'data.project_rollup.some((project) => project.project_id === "'"$PROJECT_ID"'")' "Team brief rollup missed the scenario project"
assert_json "$TEAM_BRIEF_JSON" 'data.by_member.some((member) => member.member_id === "'"$WORKER_ID"'" && member.task_count === 1)' "Team brief missed claimed worker workload"
assert_json "$TEAM_BRIEF_JSON" 'data.rendered_text.includes("Team Brief: Core Team")' "Team brief did not render the expected title"

scenario_log "Scheduling team brief"
TEAM_SCHEDULE_JSON="$(run_json node bin/artifact-loop.js team schedule-brief "$TEAM_ID" \
  --owner-worker "$LEAD_ID" \
  --timezone America/New_York \
  --delivery-hour 9 \
  --service-url "$SERVICE_URL" \
  --json)"
TEAM_NEXT_RUN_AT="$(json_field "$TEAM_SCHEDULE_JSON" 'data.next_run_at')"
[[ -n "$TEAM_NEXT_RUN_AT" ]] || scenario_die "Team brief schedule next_run_at was empty"

scenario_log "Running scheduled briefs if due"
TEAM_BRIEF_RUN_JSON="$(run_json node bin/artifact-loop.js run-scheduled-briefs --data-dir "$SERVICE_DATA_DIR" --json)"
TEAM_GENERATED_COUNT="$(json_field "$TEAM_BRIEF_RUN_JSON" 'data.generated_team_ids.filter((id) => id === "'"$TEAM_ID"'").length')"

if [[ "$TEAM_GENERATED_COUNT" == "0" ]]; then
  scenario_log "Team brief is not due yet; forcing execution at persisted next_run_at"
  FORCED_TEAM_BRIEF_JSON="$(
    node --input-type=module -e '
      import { createEngine } from "./dist/src/engine.js";
      const [dataDir, teamId] = process.argv.slice(1);
      const engine = createEngine({ dataDir });
      const schedule = engine.getTeamBriefSchedule(teamId);
      if (!schedule?.next_run_at) {
        process.exit(1);
      }
      const result = engine.runScheduledBriefs(new Date(schedule.next_run_at));
      console.log(JSON.stringify(result, null, 2));
    ' "$SERVICE_DATA_DIR" "$TEAM_ID"
  )"
  assert_json "$FORCED_TEAM_BRIEF_JSON" 'data.generated_team_ids.includes("'"$TEAM_ID"'")' "Forced team brief run did not generate a team brief"
else
  assert_json "$TEAM_BRIEF_RUN_JSON" 'data.generated_team_ids.includes("'"$TEAM_ID"'")' "Scheduled team brief run did not generate a team brief"
fi

LATEST_TEAM_BRIEF_JSON="$(http_json GET "${SERVICE_URL}/teams/${TEAM_ID}/brief-runs/latest?requested_by_worker_id=${LEAD_ID}")"
TEAM_BRIEF_RUN_ID="$(json_field "$LATEST_TEAM_BRIEF_JSON" 'data.id')"
assert_json "$LATEST_TEAM_BRIEF_JSON" 'data.team_id === "'"$TEAM_ID"'"' "Latest team brief run returned the wrong team id"
assert_json "$LATEST_TEAM_BRIEF_JSON" 'data.brief.project_rollup.some((project) => project.project_id === "'"$PROJECT_ID"'")' "Latest team brief run missed the scenario project"

scenario_log "Seeding isolated legacy adoption fixture"
seed_legacy_adoption_fixture "$LEGACY_DATA_DIR"
ADOPTION_DRY_RUN_JSON="$(run_json node bin/artifact-loop.js org adopt-existing \
  --org-id org-legacy \
  --org-name "Legacy Org" \
  --org-timezone America/New_York \
  --team-id team-legacy \
  --team-name "Legacy Team" \
  --team-description "Default adopted team" \
  --data-dir "$LEGACY_DATA_DIR" \
  --json)"
assert_json "$ADOPTION_DRY_RUN_JSON" 'data.ready === true' "Adoption dry run was not ready"
assert_json "$ADOPTION_DRY_RUN_JSON" 'data.project_backfills.some((item) => item.project_id === "proj-legacy" && item.team_id === "team-legacy")' "Adoption dry run missed the legacy project backfill"

ADOPTION_APPLY_JSON="$(run_json node bin/artifact-loop.js org adopt-existing \
  --org-id org-legacy \
  --org-name "Legacy Org" \
  --org-timezone America/New_York \
  --team-id team-legacy \
  --team-name "Legacy Team" \
  --team-description "Default adopted team" \
  --apply \
  --data-dir "$LEGACY_DATA_DIR" \
  --json)"
ADOPTION_REPORT_PATH="$(json_field "$ADOPTION_APPLY_JSON" 'data.report_path')"
assert_json "$ADOPTION_APPLY_JSON" 'data.applied === true' "Adoption apply did not report applied=true"
[[ -f "$ADOPTION_REPORT_PATH" ]] || scenario_die "Adoption report was not written to disk"

ADOPTION_STATUS_JSON="$(run_json node bin/artifact-loop.js org adoption-status --data-dir "$LEGACY_DATA_DIR" --json)"
assert_json "$ADOPTION_STATUS_JSON" 'data.has_report === true' "Adoption status did not report a saved adoption report"
assert_json "$ADOPTION_STATUS_JSON" 'data.report.plan.project_backfills.some((item) => item.project_id === "proj-legacy" && item.team_id === "team-legacy")' "Adoption status missed the project backfill"

scenario_log "Writing smoke summary"
node --input-type=module -e '
  import { writeFileSync } from "node:fs";
  const [
    reportPath,
    serviceUrl,
    inviteId,
    workerId,
    projectId,
    taskId,
    teamBriefRunId,
    adoptionReportPath,
  ] = process.argv.slice(1);
  const lines = [
    "# Org Surface Smoke v1",
    "",
    "## Verified Surfaces",
    "- CLI invite creation",
    "- HTTP invite claim",
    "- CLI project/task coordination to ready_for_review",
    "- HTTP team projects/summary/brief reads",
    "- Team brief schedule plus latest persisted run",
    "- CLI adopt-existing dry-run/apply/status",
    "",
    "## Identifiers",
    `- service_url: ${serviceUrl}`,
    `- invite_id: ${inviteId}`,
    `- claimed_member_id: ${workerId}`,
    `- project_id: ${projectId}`,
    `- task_id: ${taskId}`,
    `- team_brief_run_id: ${teamBriefRunId}`,
    `- adoption_report_path: ${adoptionReportPath}`,
  ];
  writeFileSync(reportPath, `${lines.join("\n")}\n`, "utf8");
  console.log(lines.join("\n"));
' "$REPORT_PATH" "$SERVICE_URL" "$INVITE_ID" "$WORKER_ID" "$PROJECT_ID" "$TASK_ID" "$TEAM_BRIEF_RUN_ID" "$ADOPTION_REPORT_PATH"

if [[ -n "$MANIFEST_PATH" ]]; then
  mkdir -p "$(dirname "$MANIFEST_PATH")"
  node --input-type=module -e '
    import { writeFileSync } from "node:fs";
    const manifest = {
      tmp_root: process.argv[1],
      service_url: process.argv[2],
      service_data_dir: process.argv[3],
      lead_data_dir: process.argv[4],
      worker_data_dir: process.argv[5],
      legacy_data_dir: process.argv[6],
      report_path: process.argv[7],
      org_id: process.argv[8],
      team_id: process.argv[9],
      lead_id: process.argv[10],
      lead_agent_id: process.argv[11],
      worker_id: process.argv[12],
      worker_agent_id: process.argv[13],
      invite_id: process.argv[14],
      project_id: process.argv[15],
      task_id: process.argv[16],
      message_id: process.argv[17],
      team_brief_run_id: process.argv[18],
      adoption_report_path: process.argv[19],
      keep_alive: process.argv[20] === "1",
      service_pid: process.argv[21] ? Number(process.argv[21]) : undefined,
    };
    writeFileSync(process.argv[22], `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  ' \
    "$TMP_ROOT" \
    "$SERVICE_URL" \
    "$SERVICE_DATA_DIR" \
    "$LEAD_DATA_DIR" \
    "$WORKER_DATA_DIR" \
    "$LEGACY_DATA_DIR" \
    "$REPORT_PATH" \
    "$ORG_ID" \
    "$TEAM_ID" \
    "$LEAD_ID" \
    "$LEAD_AGENT_ID" \
    "$WORKER_ID" \
    "$WORKER_AGENT_ID" \
    "$INVITE_ID" \
    "$PROJECT_ID" \
    "$TASK_ID" \
    "$MESSAGE_ID" \
    "$TEAM_BRIEF_RUN_ID" \
    "$ADOPTION_REPORT_PATH" \
    "$KEEP_ALIVE" \
    "${SERVICE_PID:-}" \
    "$MANIFEST_PATH"
fi

echo
echo "PASS org_surface_smoke_v1"
echo "  tmp_root: $TMP_ROOT"
echo "  service_url: $SERVICE_URL"
echo "  invite_id: $INVITE_ID"
echo "  project_id: $PROJECT_ID"
echo "  task_id: $TASK_ID"
echo "  team_brief_run_id: $TEAM_BRIEF_RUN_ID"
echo "  adoption_report_path: $ADOPTION_REPORT_PATH"
echo "  report_path: $REPORT_PATH"
if [[ "$KEEP_ALIVE" == "1" ]]; then
  echo "  keep_alive: true"
fi
if [[ -n "$MANIFEST_PATH" ]]; then
  echo "  manifest_path: $MANIFEST_PATH"
fi
