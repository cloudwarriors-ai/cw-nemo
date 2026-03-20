#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ARTIFACT_LOOP_HUB_HOST="${ARTIFACT_LOOP_HUB_HOST:-127.0.0.1}"
ARTIFACT_LOOP_HUB_PORT="${ARTIFACT_LOOP_HUB_PORT:-4080}"
ARTIFACT_LOOP_HUB_TAILSCALE_HTTPS_PORT="${ARTIFACT_LOOP_HUB_TAILSCALE_HTTPS_PORT:-4443}"
ARTIFACT_LOOP_HUB_URL="${ARTIFACT_LOOP_HUB_URL:-https://nemoclaw.tailcc6c5f.ts.net:${ARTIFACT_LOOP_HUB_TAILSCALE_HTTPS_PORT}}"
ARTIFACT_LOOP_HUB_DATA_DIR="${ARTIFACT_LOOP_HUB_DATA_DIR:-${HOME}/.artifact-loop/team-hub}"
ARTIFACT_LOOP_HUB_PID_FILE="${ARTIFACT_LOOP_HUB_PID_FILE:-${ARTIFACT_LOOP_HUB_DATA_DIR}/artifact-loop-hub.pid}"
ARTIFACT_LOOP_HUB_STDOUT_LOG="${ARTIFACT_LOOP_HUB_STDOUT_LOG:-${ARTIFACT_LOOP_HUB_DATA_DIR}/artifact-loop-hub.stdout.log}"
ARTIFACT_LOOP_HUB_STDERR_LOG="${ARTIFACT_LOOP_HUB_STDERR_LOG:-${ARTIFACT_LOOP_HUB_DATA_DIR}/artifact-loop-hub.stderr.log}"
ARTIFACT_LOOP_HUB_HEALTH_URL="http://${ARTIFACT_LOOP_HUB_HOST}:${ARTIFACT_LOOP_HUB_PORT}/health"

hub_log() {
  echo "==> $*"
}

hub_die() {
  echo "ERROR: $*" >&2
  exit 1
}

hub_require_command() {
  command -v "$1" >/dev/null 2>&1 || hub_die "Missing required command: $1"
}

hub_ensure_data_dir() {
  mkdir -p "$ARTIFACT_LOOP_HUB_DATA_DIR"
}

hub_is_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

hub_read_pid() {
  if [[ -f "$ARTIFACT_LOOP_HUB_PID_FILE" ]]; then
    tr -d '[:space:]' <"$ARTIFACT_LOOP_HUB_PID_FILE"
  fi
}

hub_clear_stale_pid_file() {
  local pid
  pid="$(hub_read_pid)"
  if [[ -n "$pid" ]] && ! hub_is_pid_running "$pid"; then
    rm -f "$ARTIFACT_LOOP_HUB_PID_FILE"
  fi
}

hub_port_listener_output() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$ARTIFACT_LOOP_HUB_PORT" -sTCP:LISTEN 2>/dev/null || true
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | awk -v port=":${ARTIFACT_LOOP_HUB_PORT}" '$4 ~ port { print }' || true
    return
  fi
  hub_die "Neither lsof nor ss is available to inspect listeners"
}

hub_assert_port_available() {
  local listeners
  listeners="$(hub_port_listener_output)"
  if [[ -n "$listeners" ]]; then
    echo "$listeners" >&2
    hub_die "Port ${ARTIFACT_LOOP_HUB_PORT} is already in use"
  fi
}

hub_assert_local_binding_only() {
  local listeners
  listeners="$(hub_port_listener_output)"
  [[ -n "$listeners" ]] || hub_die "No listener found on port ${ARTIFACT_LOOP_HUB_PORT}"

  if command -v lsof >/dev/null 2>&1; then
    grep -Eq "(127\\.0\\.0\\.1|localhost):${ARTIFACT_LOOP_HUB_PORT}" <<<"$listeners" \
      || hub_die "Artifact Loop hub is not bound to localhost only"
    if grep -Eq "(\\*:${ARTIFACT_LOOP_HUB_PORT}|\\[::\\]:${ARTIFACT_LOOP_HUB_PORT}|0\\.0\\.0\\.0:${ARTIFACT_LOOP_HUB_PORT})" <<<"$listeners"; then
      hub_die "Artifact Loop hub appears to be exposed beyond localhost"
    fi
    return
  fi

  grep -Eq "(127\\.0\\.0\\.1|\\[::1\\]|localhost):${ARTIFACT_LOOP_HUB_PORT}" <<<"$listeners" \
    || hub_die "Artifact Loop hub is not bound to localhost only"
}

hub_wait_for_health() {
  local attempts="${1:-100}"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$ARTIFACT_LOOP_HUB_HEALTH_URL" >/dev/null 2>&1; then
      return
    fi
    sleep 0.1
  done
  hub_die "Artifact Loop hub did not become healthy at ${ARTIFACT_LOOP_HUB_HEALTH_URL}"
}
