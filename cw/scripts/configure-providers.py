#!/usr/bin/env python3
"""Inject CW model providers (Anthropic, OpenAI, OpenRouter) into openclaw.json.

Runs at container startup via cw-start.sh. Only adds providers whose
API key env vars are set; never removes existing providers.
"""

import json
import os

path = os.path.expanduser("~/.openclaw/openclaw.json")
os.makedirs(os.path.dirname(path), exist_ok=True)

cfg = {}
if os.path.exists(path):
    with open(path) as f:
        cfg = json.load(f)

providers = cfg.setdefault("models", {}).setdefault("providers", {})

# Anthropic (primary for CW)
if os.environ.get("ANTHROPIC_API_KEY"):
    providers["anthropic"] = {
        "apiKey": os.environ["ANTHROPIC_API_KEY"],
        "api": "anthropic",
        "models": [{"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"}],
    }
    cfg.setdefault("agents", {}).setdefault("defaults", {}).setdefault("model", {})[
        "primary"
    ] = "anthropic/claude-sonnet-4-6"

# OpenRouter
if os.environ.get("OPENROUTER_API_KEY"):
    providers["openrouter"] = {
        "baseUrl": "https://openrouter.ai/api/v1",
        "apiKey": os.environ["OPENROUTER_API_KEY"],
        "api": "openai-completions",
    }

# OpenAI
if os.environ.get("OPENAI_API_KEY"):
    providers["openai"] = {
        "apiKey": os.environ["OPENAI_API_KEY"],
        "api": "openai-completions",
    }

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
os.chmod(path, 0o600)
