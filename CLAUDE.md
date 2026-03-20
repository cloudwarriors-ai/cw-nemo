# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is NemoClaw

NemoClaw is an NVIDIA project that runs OpenClaw autonomous assistants inside OpenShell sandboxes. It provides sandbox lifecycle management, inference routing to NVIDIA cloud APIs or local providers, and runtime security policy enforcement. Currently alpha/pre-production.

## Build & Development Commands

```bash
# Initial setup
npm install                                    # Root deps (OpenClaw SDK)
cd nemoclaw && npm install && npm run build    # TypeScript plugin
cd nemoclaw-blueprint && uv sync               # Python blueprint deps

# TypeScript plugin (in nemoclaw/)
npm run build          # Compile with tsc
npm run dev            # Watch mode
npm run check          # Lint + format check + typecheck (all-in-one)
npm run test           # Vitest
npm run test:watch     # Vitest watch mode

# Root-level tests
npm test               # node --test test/*.test.js

# All linting (from repo root)
make check             # TS lint/format/typecheck + Python ruff

# Auto-format (from repo root)
make format            # Prettier + ruff

# Docs
make docs              # Sphinx build
make docs-live         # Auto-rebuild with browser
```

## Architecture

**Three-layer stack:**

1. **Host CLI** (`bin/nemoclaw.js` + `bin/lib/`) — JavaScript entry point for host-side commands (`nemoclaw onboard`, `nemoclaw list`, `nemoclaw <name> connect`). Runs outside the sandbox.

2. **OpenClaw Plugin** (`nemoclaw/src/`, TypeScript) — Registers into the OpenClaw runtime via the plugin API (`index.ts:register()`). Provides:
   - Slash command `/nemoclaw` for chat interface (`commands/slash.ts`)
   - CLI subcommands via Commander.js (`cli.ts` → `commands/*.ts`)
   - NVIDIA NIM inference provider registration
   - The plugin calls the Python blueprint runner via subprocess (`blueprint/exec.ts`)

3. **Blueprint Orchestrator** (`nemoclaw-blueprint/`, Python) — `orchestrator/runner.py` handles plan/apply/status/rollback lifecycle. Drives `openshell` CLI to create sandboxes, configure inference providers, and manage network policies. Uses a stdout protocol (`PROGRESS:<pct>:<label>`, `RUN_ID:<id>`) for communication with the TS plugin.

**Key data flows:**
- Bootstrap: plugin → blueprint runner (plan → apply) → `openshell sandbox create`
- Migration: host OpenClaw state → snapshot (`migrations/snapshot.py`) → tar → sandbox restore
- Inference: agent in sandbox → OpenShell gateway → NVIDIA cloud API
- Blueprint artifacts distributed via OCI registry (GHCR) or GitHub releases, fetched by `blueprint/fetch.ts` and verified by `blueprint/verify.ts`

## Conventions

- **Commit messages**: Conventional Commits format — `feat(scope):`, `fix(scope):`, `docs:`, `chore:`, etc.
- **License headers**: All source files require `SPDX-FileCopyrightText` and `SPDX-License-Identifier: Apache-2.0` headers.
- **Plugin SDK types**: Defined locally in `nemoclaw/src/index.ts` as stubs because the real OpenClaw SDK is only available at runtime, not build time.
- **No `shell=True`**: The Python runner uses `subprocess.run()` with argv lists exclusively.
- **TypeScript strict mode**: `tsconfig.json` enforces strict compilation.
- **Python formatting**: ruff (not black/isort). Check with `cd nemoclaw-blueprint && make check`.
- **E2E tests** require Docker: `docker build -f test/Dockerfile.sandbox -t nemoclaw-sandbox-test . && docker run --rm -v "$PWD/test:/opt/test" nemoclaw-sandbox-test /opt/test/e2e-test.sh`
