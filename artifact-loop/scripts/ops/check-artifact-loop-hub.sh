#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/artifact-loop-hub-common.sh"

hub_require_command curl

hub_ensure_data_dir
hub_clear_stale_pid_file

hub_log "Checking Artifact Loop hub"
[[ -d "$ARTIFACT_LOOP_HUB_DATA_DIR" ]] || hub_die "Hub data dir is missing: $ARTIFACT_LOOP_HUB_DATA_DIR"

hub_wait_for_health 10
hub_assert_local_binding_only

brief_runner_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run-artifact-loop-briefs.sh"
[[ -f "$brief_runner_script" ]] || hub_die "Brief runner script is missing: $brief_runner_script"
grep -Fq 'source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/artifact-loop-hub-common.sh"' "$brief_runner_script" \
  || hub_die "Brief runner does not source the shared hub defaults"
grep -Fq 'node bin/artifact-loop.js run-scheduled-briefs --data-dir "$ARTIFACT_LOOP_HUB_DATA_DIR" "$@"' "$brief_runner_script" \
  || hub_die "Brief runner is not pinned to the shared hub data dir"

brief_cmd="node bin/artifact-loop.js run-scheduled-briefs --data-dir \"$ARTIFACT_LOOP_HUB_DATA_DIR\""

echo "PASS artifact_loop_hub_check"
echo "  health_url: $ARTIFACT_LOOP_HUB_HEALTH_URL"
echo "  data_dir: $ARTIFACT_LOOP_HUB_DATA_DIR"
echo "  pid_file: $ARTIFACT_LOOP_HUB_PID_FILE"
echo "  brief_runner: $brief_cmd"
