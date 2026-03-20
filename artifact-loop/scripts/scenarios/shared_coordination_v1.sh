#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
source "$ROOT_DIR/scripts/scenarios/lib/shared-coordination-common.sh"

TMP_ROOT="${ARTIFACT_LOOP_SCENARIO_TMPDIR:-$(mktemp -d /tmp/artifact-loop-shared-coordination-XXXXXX)}"
SERVICE_DATA_DIR="$TMP_ROOT/service-data"
LEAD_DATA_DIR="$TMP_ROOT/lead-data"
WORKER_DATA_DIR="$TMP_ROOT/worker-data"
MANIFEST_PATH="${ARTIFACT_LOOP_SCENARIO_MANIFEST_PATH:-}"
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

PROJECT_ID="proj-core"
ORG_ID="org-core"
TEAM_ID="team-core"
LEAD_ID="lead-1"
LEAD_AGENT_ID="lead-agent-1"
WORKER_ID="worker-1"
WORKER_AGENT_ID="worker-agent-1"

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

mkdir -p "$SERVICE_DATA_DIR" "$LEAD_DATA_DIR" "$WORKER_DATA_DIR"

PROJECT_TITLE="Core Project"
PROJECT_DESCRIPTION="Shared coordination smoke scenario"
PROJECT_GOAL="Validate the shared lead/worker coordination loop"
PROJECT_DELIVERABLE="Verified loop"
PROJECT_CONSTRAINT="CLI only"
PROJECT_DEFINITION_OF_DONE="Lead can assign, worker can report, brief reflects truth"

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

scenario_log "Bootstrapping organization and team"
run_cmd node bin/artifact-loop.js org bootstrap \
  --org-id "$ORG_ID" \
  --org-name "Core Org" \
  --org-timezone America/New_York \
  --team-id "$TEAM_ID" \
  --team-name "Core Team" \
  --team-description "Shared coordination team" \
  --member-id "$LEAD_ID" \
  --member-name Lead \
  --member-timezone America/New_York \
  --agent-id "$LEAD_AGENT_ID" \
  --agent-label "Lead Agent" \
  --agent-connector lead-cli \
  --service-url "$SERVICE_URL"
run_cmd node bin/artifact-loop.js team add-member "$TEAM_ID" \
  --member "$WORKER_ID" \
  --role worker \
  --by "$LEAD_ID" \
  --name Worker \
  --timezone America/New_York \
  --worker-role worker \
  --service-url "$SERVICE_URL"
run_cmd node bin/artifact-loop.js worker add-agent "$WORKER_ID" --id "$WORKER_AGENT_ID" --label "Worker Agent" --connector remote --service-url "$SERVICE_URL"

run_shared_coordination_flow

scenario_log "Scheduling brief"
SCHEDULE_JSON="$(run_json node bin/artifact-loop.js project schedule-brief "$PROJECT_ID" --owner-worker "$LEAD_ID" --timezone America/New_York --delivery-hour 9 --service-url "$SERVICE_URL" --json)"
NEXT_RUN_AT="$(json_field "$SCHEDULE_JSON" 'data.next_run_at')"
[[ -n "$NEXT_RUN_AT" ]] || scenario_die "Brief schedule next_run_at was empty"

scenario_log "Running scheduled brief if due"
BRIEF_RUN_JSON="$(run_json node bin/artifact-loop.js run-scheduled-briefs --data-dir "$SERVICE_DATA_DIR" --json)"
GENERATED_COUNT="$(json_field "$BRIEF_RUN_JSON" 'data.generated_count')"

if [[ "$GENERATED_COUNT" == "0" ]]; then
  scenario_log "Brief schedule is not due yet; forcing execution at persisted next_run_at to validate brief-run persistence"
  FORCED_BRIEF_JSON="$(
    node --input-type=module -e "
      import { createEngine } from './dist/src/engine.js';
      const engine = createEngine({ dataDir: process.argv[1] });
      const schedule = engine.getProjectBriefSchedule(process.argv[2]);
      const result = engine.runScheduledBriefs(new Date(schedule.next_run_at));
      console.log(JSON.stringify(result, null, 2));
    " "$SERVICE_DATA_DIR" "$PROJECT_ID"
  )"
  GENERATED_COUNT="$(json_field "$FORCED_BRIEF_JSON" 'data.generated_count')"
  assert_json "$FORCED_BRIEF_JSON" 'data.generated_count === 1' "Forced brief run did not generate a brief"
else
  assert_json "$BRIEF_RUN_JSON" 'data.generated_count >= 1' "Scheduled brief run did not generate a brief"
fi

scenario_log "Validating latest brief run"
LATEST_BRIEF_JSON="$(run_json node bin/artifact-loop.js project brief "$PROJECT_ID" --latest-run --service-url "$SERVICE_URL" --json)"
assert_json "$LATEST_BRIEF_JSON" 'data.brief.snapshot.counts_by_status.ready_for_review === 1' "Latest brief snapshot missing ready_for_review state"
assert_json "$LATEST_BRIEF_JSON" 'data.brief.by_worker.some((group) => group.worker_id === "'"$WORKER_ID"'" && group.tasks.some((task) => task.id === "'"$TASK_ID"'"))' "Latest brief by_worker missing worker activity"
assert_json "$LATEST_BRIEF_JSON" 'data.brief.recent_movement.some((item) => item.task_id === "'"$TASK_ID"'")' "Latest brief missing task movement"
assert_json "$LATEST_BRIEF_JSON" 'data.brief.lead_attention_items.some((item) => item.kind === "ready_for_review" && item.task.id === "'"$TASK_ID"'")' "Latest brief missing lead attention item"

scenario_log "Rendering human brief"
run_cmd node bin/artifact-loop.js project brief "$PROJECT_ID" --service-url "$SERVICE_URL"

write_shared_coordination_manifest "$MANIFEST_PATH"

echo
echo "PASS shared_coordination_v1"
echo "  tmp_root: $TMP_ROOT"
echo "  service_url: $SERVICE_URL"
echo "  project_id: $PROJECT_ID"
echo "  org_id: $ORG_ID"
echo "  team_id: $TEAM_ID"
echo "  task_id: $TASK_ID"
echo "  assignment_inbox_id: $ASSIGNMENT_INBOX_ID"
echo "  message_id: $MESSAGE_ID"
if [[ "$KEEP_ALIVE" == "1" ]]; then
  echo "  keep_alive: true"
fi
if [[ -n "$MANIFEST_PATH" ]]; then
  echo "  manifest_path: $MANIFEST_PATH"
fi
