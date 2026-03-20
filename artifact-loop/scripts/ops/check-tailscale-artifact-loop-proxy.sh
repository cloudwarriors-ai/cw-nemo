#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/artifact-loop-hub-common.sh"

hub_require_command tailscale
hub_require_command curl

hub_log "Checking Tailscale Serve configuration for Artifact Loop hub"
status_json="$(tailscale serve status --json)"
node --input-type=module -e '
  const [raw, port, target] = process.argv.slice(1);
  const text = JSON.stringify(JSON.parse(raw));
  if (!text.includes(port)) {
    console.error(`Serve status missing HTTPS port ${port}`);
    process.exit(1);
  }
  if (!text.includes(target)) {
    console.error(`Serve status missing target ${target}`);
    process.exit(1);
  }
' "$status_json" "$ARTIFACT_LOOP_HUB_TAILSCALE_HTTPS_PORT" "http://${ARTIFACT_LOOP_HUB_HOST}:${ARTIFACT_LOOP_HUB_PORT}" \
  || hub_die "Tailscale Serve status does not match expected hub proxy"

if tailscale funnel status --json >/dev/null 2>&1; then
  funnel_json="$(tailscale funnel status --json)"
  node --input-type=module -e '
    const [raw, port] = process.argv.slice(1);
    const text = JSON.stringify(JSON.parse(raw));
    if (text.includes(port)) {
      console.error(`Funnel appears enabled for port ${port}`);
      process.exit(1);
    }
  ' "$funnel_json" "$ARTIFACT_LOOP_HUB_TAILSCALE_HTTPS_PORT" \
    || hub_die "Artifact Loop hub must remain tailnet-only; Funnel appears enabled"
fi

curl -fsS "${ARTIFACT_LOOP_HUB_URL}/health" >/dev/null || hub_die "Tailnet health check failed at ${ARTIFACT_LOOP_HUB_URL}/health"

echo "PASS tailscale_artifact_loop_proxy_check"
echo "  hub_url: $ARTIFACT_LOOP_HUB_URL"
echo "  target: http://${ARTIFACT_LOOP_HUB_HOST}:${ARTIFACT_LOOP_HUB_PORT}"
