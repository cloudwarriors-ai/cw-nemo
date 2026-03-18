#!/usr/bin/env bash
# CW entrypoint wrapper — overlays CW config on top of NemoClaw, then
# delegates to the upstream nemoclaw-start entrypoint.
set -euo pipefail

# Overlay CW skills/agents into OpenClaw directories
mkdir -p ~/.openclaw/skills ~/.openclaw/llm-skills ~/.openclaw/agents
cp -rn /opt/cw-skills/* ~/.openclaw/skills/ 2>/dev/null || true
cp -rn /opt/cw-llm-skills/* ~/.openclaw/llm-skills/ 2>/dev/null || true
cp -rn /opt/cw-agents/* ~/.openclaw/agents/ 2>/dev/null || true
cp /opt/cw-config/AGENTS.md ~/.openclaw/AGENTS.md 2>/dev/null || true

# Reconfigure model providers: add Anthropic, OpenAI, OpenRouter alongside NVIDIA
python3 /opt/cw-config/configure-providers.py

# Apply CW network policy overlay (ZW2, Tesseract, Anthropic, etc.)
if [ -f /opt/cw-blueprint-overlay/policies/presets/cloudwarriors.yaml ]; then
  openshell policy set --merge /opt/cw-blueprint-overlay/policies/presets/cloudwarriors.yaml 2>/dev/null || true
fi

# Delegate to upstream NemoClaw entrypoint
exec /usr/local/bin/nemoclaw-start "$@"
