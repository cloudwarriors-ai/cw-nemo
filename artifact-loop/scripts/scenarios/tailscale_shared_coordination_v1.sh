#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
source "$ROOT_DIR/scripts/scenarios/lib/shared-coordination-common.sh"

TMP_ROOT="${ARTIFACT_LOOP_SCENARIO_TMPDIR:-$(mktemp -d /tmp/artifact-loop-tailscale-coordination-XXXXXX)}"
LEAD_DATA_DIR="$TMP_ROOT/lead-data"
WORKER_DATA_DIR="$TMP_ROOT/worker-data"
MANIFEST_PATH="${ARTIFACT_LOOP_SCENARIO_MANIFEST_PATH:-}"
KEEP_ALIVE="${ARTIFACT_LOOP_SCENARIO_KEEP_ALIVE:-0}"
VALIDATE_ONLY="${ARTIFACT_LOOP_TAILSCALE_VALIDATE_ONLY:-0}"
EXPECTED_HUB_URL="${ARTIFACT_LOOP_HUB_URL:-https://nemoclaw.tailcc6c5f.ts.net:4443}"
SERVICE_URL="${ARTIFACT_LOOP_SERVICE_URL:-}"

ORG_ID="${ARTIFACT_LOOP_ORG_ID:-org-core}"
TEAM_ID="${ARTIFACT_LOOP_TEAM_ID:-team-core}"
LEAD_ID="${ARTIFACT_LOOP_LEAD_ID:-lead-1}"
LEAD_AGENT_ID="${ARTIFACT_LOOP_LEAD_AGENT_ID:-lead-agent-1}"
WORKER_ID="${ARTIFACT_LOOP_WORKER_ID:-worker-1}"
WORKER_AGENT_ID="${ARTIFACT_LOOP_WORKER_AGENT_ID:-worker-agent-1}"

RUN_ID="${ARTIFACT_LOOP_TAILSCALE_RUN_ID:-$(date +%s)}"
PROJECT_ID="${ARTIFACT_LOOP_PROJECT_ID:-proj-tailnet-${RUN_ID}}"
PROJECT_TITLE="${ARTIFACT_LOOP_PROJECT_TITLE:-Tailnet Coordination ${RUN_ID}}"
PROJECT_DESCRIPTION="${ARTIFACT_LOOP_PROJECT_DESCRIPTION:-Shared coordination validation over a remotely hosted Artifact Loop hub}"
PROJECT_GOAL="${ARTIFACT_LOOP_PROJECT_GOAL:-Validate the shared lead/worker coordination loop over a tailnet-hosted Artifact Loop hub}"
PROJECT_DELIVERABLE="${ARTIFACT_LOOP_PROJECT_DELIVERABLE:-Tailnet verified loop}"
PROJECT_CONSTRAINT="${ARTIFACT_LOOP_PROJECT_CONSTRAINT:-Remote shared service only}"
PROJECT_DEFINITION_OF_DONE="${ARTIFACT_LOOP_PROJECT_DEFINITION_OF_DONE:-Lead can assign, worker can report, and current brief reflects truth over the tailnet hub}"

cleanup() {
  if [[ "$KEEP_ALIVE" != "1" ]]; then
    rm -rf "$TMP_ROOT"
  fi
}
trap cleanup EXIT

[[ -n "$SERVICE_URL" ]] || scenario_die "ARTIFACT_LOOP_SERVICE_URL is required"

if [[ "$VALIDATE_ONLY" == "1" ]]; then
  echo "PASS tailscale_shared_coordination_v1_args"
  echo "  service_url: $SERVICE_URL"
  echo "  expected_hub_url: $EXPECTED_HUB_URL"
  echo "  team_id: $TEAM_ID"
  echo "  lead_id: $LEAD_ID"
  echo "  worker_id: $WORKER_ID"
  echo "  project_id: $PROJECT_ID"
  exit 0
fi

mkdir -p "$LEAD_DATA_DIR" "$WORKER_DATA_DIR"

scenario_log "Building artifact-loop"
npm run build >/dev/null

scenario_log "Checking shared hub health"
curl -fsS "${SERVICE_URL}/health" >/dev/null || scenario_die "Shared hub health check failed at ${SERVICE_URL}/health"

scenario_log "Verifying expected team and actor prerequisites"
run_json node bin/artifact-loop.js org show --service-url "$SERVICE_URL" --json >/dev/null
run_json node bin/artifact-loop.js team show "$TEAM_ID" --service-url "$SERVICE_URL" --json >/dev/null
run_json node bin/artifact-loop.js worker show "$LEAD_ID" --service-url "$SERVICE_URL" --json >/dev/null
run_json node bin/artifact-loop.js worker show "$WORKER_ID" --service-url "$SERVICE_URL" --json >/dev/null
AGENTS_JSON="$(run_json node bin/artifact-loop.js worker agents "$WORKER_ID" --service-url "$SERVICE_URL" --json)"
assert_json "$AGENTS_JSON" 'data.some((agent) => agent.id === "'"$WORKER_AGENT_ID"'")' "Expected worker agent ${WORKER_AGENT_ID} to exist on the shared hub"

run_shared_coordination_flow

scenario_log "Rendering current brief"
run_cmd node bin/artifact-loop.js project brief "$PROJECT_ID" --service-url "$SERVICE_URL"

write_shared_coordination_manifest "$MANIFEST_PATH"

echo
echo "PASS tailscale_shared_coordination_v1"
echo "  service_url: $SERVICE_URL"
echo "  expected_hub_url: $EXPECTED_HUB_URL"
echo "  project_id: $PROJECT_ID"
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
