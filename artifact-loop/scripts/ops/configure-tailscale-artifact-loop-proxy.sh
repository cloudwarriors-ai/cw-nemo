#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/artifact-loop-hub-common.sh"

hub_require_command tailscale

hub_log "Configuring Tailscale Serve for Artifact Loop hub"
tailscale serve --bg --https="$ARTIFACT_LOOP_HUB_TAILSCALE_HTTPS_PORT" "http://${ARTIFACT_LOOP_HUB_HOST}:${ARTIFACT_LOOP_HUB_PORT}"

status_json="$(tailscale serve status --json)"
node --input-type=module -e '
  const [raw, port, target] = process.argv.slice(1);
  const text = JSON.stringify(JSON.parse(raw));
  if (!text.includes(port)) {
    console.error(`Tailscale Serve config missing HTTPS port ${port}`);
    process.exit(1);
  }
  if (!text.includes(target)) {
    console.error(`Tailscale Serve config missing proxy target ${target}`);
    process.exit(1);
  }
' "$status_json" "$ARTIFACT_LOOP_HUB_TAILSCALE_HTTPS_PORT" "http://${ARTIFACT_LOOP_HUB_HOST}:${ARTIFACT_LOOP_HUB_PORT}" \
  || hub_die "Tailscale Serve was not configured as expected"

hub_log "Current Tailscale Serve configuration"
tailscale serve status

echo
echo "PASS configure_tailscale_artifact_loop_proxy"
echo "  hub_url: $ARTIFACT_LOOP_HUB_URL"
echo "  proxy_target: http://${ARTIFACT_LOOP_HUB_HOST}:${ARTIFACT_LOOP_HUB_PORT}"
