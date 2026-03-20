#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

scenario_die() {
  echo "ERROR: $*" >&2
  exit 1
}

scenario_log() {
  echo "==> $*"
}

json_field() {
  local json="$1"
  local expr="$2"
  node --input-type=module -e '
    const [raw, expression] = process.argv.slice(1);
    const data = JSON.parse(raw);
    const result = Function("data", `return (${expression});`)(data);
    if (result === undefined || result === null) process.exit(2);
    if (typeof result === "object") {
      console.log(JSON.stringify(result));
    } else {
      console.log(String(result));
    }
  ' "$json" "$expr" || scenario_die "Failed to read JSON expression: $expr"
}

assert_json() {
  local json="$1"
  local expr="$2"
  local message="$3"
  node --input-type=module -e '
    const [raw, expression, message] = process.argv.slice(1);
    const data = JSON.parse(raw);
    const ok = Boolean(Function("data", `return (${expression});`)(data));
    if (!ok) {
      console.error(message);
      process.exit(1);
    }
  ' "$json" "$expr" "$message" || scenario_die "$message"
}

run_cmd() {
  scenario_log "$*"
  "$@"
}

run_json() {
  "$@"
}

validate_current_brief() {
  scenario_log "Validating current brief"
  CURRENT_BRIEF_JSON="$(run_json node bin/artifact-loop.js project brief "$PROJECT_ID" --service-url "$SERVICE_URL" --json)"
  assert_json "$CURRENT_BRIEF_JSON" 'data.snapshot.counts_by_status.ready_for_review === 1' "Current brief snapshot missing ready_for_review state"
  assert_json "$CURRENT_BRIEF_JSON" 'data.by_worker.some((group) => group.worker_id === "'"$WORKER_ID"'" && group.tasks.some((task) => task.id === "'"$TASK_ID"'"))' "Current brief missing by_worker activity"
  assert_json "$CURRENT_BRIEF_JSON" 'data.lead_attention_items.some((item) => item.kind === "ready_for_review" && item.task.id === "'"$TASK_ID"'")' "Current brief missing lead attention item"
}

run_shared_coordination_flow() {
  scenario_log "Creating project definition"
  run_cmd node bin/artifact-loop.js project create \
    --id "$PROJECT_ID" \
    --team "$TEAM_ID" \
    --title "$PROJECT_TITLE" \
    --description "$PROJECT_DESCRIPTION" \
    --owner-worker "$LEAD_ID" \
    --goal "$PROJECT_GOAL" \
    --scope "lead flow" \
    --scope "worker flow" \
    --deliverable "$PROJECT_DELIVERABLE" \
    --constraint "$PROJECT_CONSTRAINT" \
    --definition-of-done "$PROJECT_DEFINITION_OF_DONE" \
    --service-url "$SERVICE_URL"

  scenario_log "Generating and approving task drafts"
  DRAFT_SET_JSON="$(run_json node bin/artifact-loop.js project generate-drafts "$PROJECT_ID" --agent "$LEAD_AGENT_ID" --service-url "$SERVICE_URL" --json)"
  DRAFT_SET_ID="$(json_field "$DRAFT_SET_JSON" 'data.id')"
  TASK_ID="$(json_field "$DRAFT_SET_JSON" 'data.drafts[0].id')"
  [[ -n "$DRAFT_SET_ID" ]] || scenario_die "Draft set id was empty"
  [[ -n "$TASK_ID" ]] || scenario_die "Task id was empty"
  APPROVAL_JSON="$(run_json node bin/artifact-loop.js project approve-drafts "$PROJECT_ID" "$DRAFT_SET_ID" --by "$LEAD_ID" --service-url "$SERVICE_URL" --json)"
  assert_json "$APPROVAL_JSON" 'data.tasks.some((task) => task.id === "'"$TASK_ID"'")' "Approved tasks did not include ${TASK_ID}"

  scenario_log "Assigning task to worker agent"
  run_cmd node bin/artifact-loop.js task assign "$TASK_ID" --worker "$WORKER_ID" --agent "$WORKER_AGENT_ID" --by "$LEAD_ID" --service-url "$SERVICE_URL"

  scenario_log "Validating worker inbox receives assignment"
  INBOX_JSON="$(run_json node bin/artifact-loop.js worker inbox --agent "$WORKER_AGENT_ID" --service-url "$SERVICE_URL" --json)"
  ASSIGNMENT_INBOX_ID="$(json_field "$INBOX_JSON" 'data.find((item) => item.kind === "assignment" && item.task_id === "'"$TASK_ID"'").id')"
  assert_json "$INBOX_JSON" 'data.some((item) => item.kind === "assignment" && item.status === "pending" && item.task_id === "'"$TASK_ID"'")' "Assignment inbox item missing for ${TASK_ID}"

  scenario_log "Acknowledging assignment"
  run_cmd node bin/artifact-loop.js worker inbox-ack "$ASSIGNMENT_INBOX_ID" --service-url "$SERVICE_URL"
  INBOX_AFTER_ACK_JSON="$(run_json node bin/artifact-loop.js worker inbox --agent "$WORKER_AGENT_ID" --status acknowledged --service-url "$SERVICE_URL" --json)"
  assert_json "$INBOX_AFTER_ACK_JSON" 'data.some((item) => item.id === "'"$ASSIGNMENT_INBOX_ID"'" && item.status === "acknowledged")' "Assignment inbox item did not acknowledge"

  scenario_log "Worker reports progress through shared truth"
  RUN_OUTPUT="$(node bin/artifact-loop.js run \
    --task "$TASK_ID" \
    --next \
    --worker "$WORKER_ID" \
    --worker-agent "$WORKER_AGENT_ID" \
    --service-url "$SERVICE_URL" \
    --data-dir "$WORKER_DATA_DIR" \
    -- node -e "process.exit(0)")"
  echo "$RUN_OUTPUT"
  grep -q "status: ready_for_review" <<<"$RUN_OUTPUT" || scenario_die "Worker run did not move task to ready_for_review"

  scenario_log "Validating project summary and worker grouping"
  SUMMARY_JSON="$(run_json node bin/artifact-loop.js project summary "$PROJECT_ID" --service-url "$SERVICE_URL" --json)"
  assert_json "$SUMMARY_JSON" 'data.counts_by_status.ready_for_review === 1' "Project summary did not report ready_for_review=1"
  assert_json "$SUMMARY_JSON" 'data.buckets.ready_for_review.some((task) => task.id === "'"$TASK_ID"'")' "Task missing from ready_for_review bucket"
  WORKERS_JSON="$(run_json node bin/artifact-loop.js project workers "$PROJECT_ID" --service-url "$SERVICE_URL" --json)"
  assert_json "$WORKERS_JSON" 'data.by_human.some((group) => group.assignee_human_id === "'"$WORKER_ID"'" && group.tasks.some((task) => task.id === "'"$TASK_ID"'"))' "Worker summary missing human grouping"
  assert_json "$WORKERS_JSON" 'data.by_agent.some((group) => group.assignee_agent_id === "'"$WORKER_AGENT_ID"'" && group.tasks.some((task) => task.id === "'"$TASK_ID"'"))' "Worker summary missing agent grouping"

  scenario_log "Sending task-scoped ping from lead to worker agent"
  PING_JSON="$(run_json node bin/artifact-loop.js task ping "$TASK_ID" --from-worker "$LEAD_ID" --from-agent "$LEAD_AGENT_ID" --to-worker "$WORKER_ID" --to-agent "$WORKER_AGENT_ID" --body "Please confirm progress" --service-url "$SERVICE_URL" --json)"
  MESSAGE_ID="$(json_field "$PING_JSON" 'data.id')"
  [[ -n "$MESSAGE_ID" ]] || scenario_die "Message id was empty"

  scenario_log "Validating message visibility and acknowledgement"
  WORKER_MESSAGES_JSON="$(run_json node bin/artifact-loop.js worker messages --task "$TASK_ID" --agent "$WORKER_AGENT_ID" --service-url "$SERVICE_URL" --json)"
  assert_json "$WORKER_MESSAGES_JSON" 'data.some((message) => message.id === "'"$MESSAGE_ID"'" && message.body === "Please confirm progress")' "Worker message view missing ping"
  TASK_MESSAGES_JSON="$(run_json node bin/artifact-loop.js task messages "$TASK_ID" --service-url "$SERVICE_URL" --json)"
  assert_json "$TASK_MESSAGES_JSON" 'data.some((message) => message.id === "'"$MESSAGE_ID"'")' "Task message view missing ping"
  run_cmd node bin/artifact-loop.js task message-ack "$MESSAGE_ID" --service-url "$SERVICE_URL"
  TASK_MESSAGES_AFTER_ACK_JSON="$(run_json node bin/artifact-loop.js task messages "$TASK_ID" --service-url "$SERVICE_URL" --json)"
  assert_json "$TASK_MESSAGES_AFTER_ACK_JSON" 'data.some((message) => message.id === "'"$MESSAGE_ID"'" && Boolean(message.acknowledged_at))' "Message acknowledgement was not persisted"

  validate_current_brief
}

write_shared_coordination_manifest() {
  local manifest_path="$1"
  [[ -n "$manifest_path" ]] || return 0
  mkdir -p "$(dirname "$manifest_path")"
  node --input-type=module -e '
    import { writeFileSync } from "node:fs";
    const manifest = {
      tmp_root: process.argv[1],
      service_url: process.argv[2],
      service_data_dir: process.argv[3] || undefined,
      lead_data_dir: process.argv[4],
      worker_data_dir: process.argv[5],
      project_id: process.argv[6],
      org_id: process.argv[7],
      team_id: process.argv[8],
      lead_id: process.argv[9],
      lead_agent_id: process.argv[10],
      worker_id: process.argv[11],
      worker_agent_id: process.argv[12],
      task_id: process.argv[13],
      assignment_inbox_id: process.argv[14],
      message_id: process.argv[15],
      keep_alive: process.argv[16] === "1",
      service_pid: process.argv[17] ? Number(process.argv[17]) : undefined,
    };
    writeFileSync(process.argv[18], `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  ' \
    "$TMP_ROOT" \
    "$SERVICE_URL" \
    "${SERVICE_DATA_DIR:-}" \
    "$LEAD_DATA_DIR" \
    "$WORKER_DATA_DIR" \
    "$PROJECT_ID" \
    "$ORG_ID" \
    "$TEAM_ID" \
    "$LEAD_ID" \
    "$LEAD_AGENT_ID" \
    "$WORKER_ID" \
    "$WORKER_AGENT_ID" \
    "$TASK_ID" \
    "$ASSIGNMENT_INBOX_ID" \
    "$MESSAGE_ID" \
    "${KEEP_ALIVE:-0}" \
    "${SERVICE_PID:-}" \
    "$manifest_path"
}
