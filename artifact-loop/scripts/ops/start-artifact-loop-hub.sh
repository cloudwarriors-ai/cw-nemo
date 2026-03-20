#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/artifact-loop-hub-common.sh"

hub_require_command node
hub_require_command curl

cd "$ROOT_DIR"
hub_ensure_data_dir
hub_clear_stale_pid_file

existing_pid="$(hub_read_pid)"
if [[ -n "$existing_pid" ]] && hub_is_pid_running "$existing_pid"; then
  hub_die "Artifact Loop hub is already running (pid ${existing_pid}). Use check-artifact-loop-hub.sh instead."
fi

hub_assert_port_available

hub_log "Starting Artifact Loop hub"
nohup node bin/artifact-loop.js serve \
  --host "$ARTIFACT_LOOP_HUB_HOST" \
  --port "$ARTIFACT_LOOP_HUB_PORT" \
  --data-dir "$ARTIFACT_LOOP_HUB_DATA_DIR" \
  >"$ARTIFACT_LOOP_HUB_STDOUT_LOG" \
  2>"$ARTIFACT_LOOP_HUB_STDERR_LOG" &
hub_pid="$!"
echo "$hub_pid" >"$ARTIFACT_LOOP_HUB_PID_FILE"

if ! hub_is_pid_running "$hub_pid"; then
  rm -f "$ARTIFACT_LOOP_HUB_PID_FILE"
  hub_die "Artifact Loop hub process exited immediately"
fi

if ! hub_wait_for_health 100; then
  rm -f "$ARTIFACT_LOOP_HUB_PID_FILE"
  hub_die "Artifact Loop hub failed health check after startup"
fi

hub_log "Artifact Loop hub is running"
echo "  pid: $hub_pid"
echo "  data_dir: $ARTIFACT_LOOP_HUB_DATA_DIR"
echo "  health_url: $ARTIFACT_LOOP_HUB_HEALTH_URL"
echo "  stdout_log: $ARTIFACT_LOOP_HUB_STDOUT_LOG"
echo "  stderr_log: $ARTIFACT_LOOP_HUB_STDERR_LOG"
