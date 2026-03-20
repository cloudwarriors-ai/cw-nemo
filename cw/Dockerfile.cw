# CW layer on top of the upstream NemoClaw image.
# Build context is the repo root so upstream files are accessible.
#
#   docker build -f cw/Dockerfile.cw -t cw-nemo .

# --- Stage 1: build the upstream NemoClaw image ---
FROM node:22-slim AS nemoclaw-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        curl git ca-certificates jq \
        iproute2 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r sandbox && useradd -r -g sandbox -d /sandbox -s /bin/bash sandbox \
    && mkdir -p /sandbox/.openclaw /sandbox/.nemoclaw \
    && chown -R sandbox:sandbox /sandbox

RUN npm install -g openclaw@2026.3.11

RUN pip3 install --break-system-packages pyyaml

COPY nemoclaw/dist/ /opt/nemoclaw/dist/
COPY nemoclaw/openclaw.plugin.json /opt/nemoclaw/
COPY nemoclaw/package.json /opt/nemoclaw/
COPY nemoclaw-blueprint/ /opt/nemoclaw-blueprint/

WORKDIR /opt/nemoclaw
RUN npm install --omit=dev

RUN mkdir -p /sandbox/.nemoclaw/blueprints/0.1.0 \
    && cp -r /opt/nemoclaw-blueprint/* /sandbox/.nemoclaw/blueprints/0.1.0/

COPY scripts/nemoclaw-start.sh /usr/local/bin/nemoclaw-start
RUN chmod +x /usr/local/bin/nemoclaw-start

WORKDIR /sandbox

# --- Stage 2: add CW customizations ---
FROM nemoclaw-base

USER root

# Copy CW extensions and install their dependencies
COPY cw/extensions/ /opt/cw-extensions/
COPY cw/scripts/install-extensions.sh /tmp/
RUN bash /tmp/install-extensions.sh /opt/cw-extensions

# Copy CW skills, agents, config
COPY cw/skills/ /opt/cw-skills/
COPY cw/llm-skills/ /opt/cw-llm-skills/
COPY cw/agents/ /opt/cw-agents/
COPY cw/AGENTS.md /opt/cw-config/AGENTS.md

# Copy CW provider config and blueprint overlay
COPY cw/scripts/configure-providers.py /opt/cw-config/configure-providers.py
COPY cw/blueprint-overlay/ /opt/cw-blueprint-overlay/
COPY cw/claude-expert/ /opt/cw-claude-expert/

# Copy CW entrypoint wrapper
COPY cw/scripts/cw-start.sh /usr/local/bin/cw-start
RUN chmod +x /usr/local/bin/cw-start

USER sandbox

# Pre-create OpenClaw directories
RUN mkdir -p /sandbox/.openclaw/agents/main/agent \
    && chmod 700 /sandbox/.openclaw

# Register CW extensions path in openclaw.json
RUN python3 -c "\
import json, os; \
path = os.path.expanduser('~/.openclaw/openclaw.json'); \
cfg = json.load(open(path)) if os.path.exists(path) else {}; \
plugins = cfg.setdefault('plugins', {}); \
load = plugins.setdefault('load', {}); \
paths = load.setdefault('paths', []); \
[paths.append(p) for p in ['/opt/cw-extensions'] if p not in paths]; \
json.dump(cfg, open(path, 'w'), indent=2); \
os.chmod(path, 0o600)"

# Install NemoClaw plugin into OpenClaw
RUN openclaw doctor --fix > /dev/null 2>&1 || true \
    && openclaw plugins install /opt/nemoclaw > /dev/null 2>&1 || true

ENTRYPOINT ["/usr/local/bin/cw-start"]
