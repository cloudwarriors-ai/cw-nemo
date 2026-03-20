#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/artifact-loop-hub-common.sh"

hub_require_command node

cd "$ROOT_DIR"
[[ -d "$ARTIFACT_LOOP_HUB_DATA_DIR" ]] || hub_die "Hub data dir is missing: $ARTIFACT_LOOP_HUB_DATA_DIR"

hub_log "Running scheduled briefs for Doug-owned hub data dir"
node bin/artifact-loop.js run-scheduled-briefs --data-dir "$ARTIFACT_LOOP_HUB_DATA_DIR" "$@"
