// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { resolve } from "node:path";
import { createClientStateStore, resolveServiceUrl, SessionHubClient } from "./client.js";
import { listenSessionHubServer } from "./server.js";

function usage() {
  return `session-hub

Usage:
  session-hub serve [--host <host>] [--port <port>] [--data-dir <dir>]
  session-hub connect <session-id> --agent <agent-id> --service-url <url> [--data-dir <dir>] [--json]
  session-hub send --body <text> [--session <session-id>] [--agent <agent-id>] [--service-url <url>] [--data-dir <dir>] [--json]
  session-hub read [--session <session-id>] [--service-url <url>] [--data-dir <dir>] [--since <iso>] [--limit <n>] [--json]

Environment:
  SESSION_HUB_SERVICE_URL
`;
}

function toCamel(flag) {
  return flag.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}

function parseArgs(args) {
  const positionals = [];
  const options = {};

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (!arg.startsWith("--")) {
      positionals.push(arg);
      continue;
    }

    const key = toCamel(arg.slice(2));
    if (key === "json") {
      options.json = true;
      continue;
    }

    const value = args[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`Missing value for ${arg}`);
    }
    options[key] = value;
    index += 1;
  }

  return { positionals, options };
}

function write(io, stream, message) {
  io[stream].write(`${message}\n`);
}

function requireValue(value, message) {
  if (!value || !String(value).trim()) {
    throw new Error(message);
  }
  return String(value).trim();
}

function resolveClientContext(options, state, { requireSession = false, requireAgent = false } = {}) {
  const serviceUrl = resolveServiceUrl(options.serviceUrl, state);
  const sessionId = options.session ?? state?.session_id;
  const agentId = options.agent ?? state?.agent_id;

  if (!serviceUrl) {
    throw new Error("A service URL is required. Pass --service-url or set SESSION_HUB_SERVICE_URL.");
  }
  if (requireSession && !sessionId) {
    throw new Error("A session is required. Connect first or pass --session.");
  }
  if (requireAgent && !agentId) {
    throw new Error("An agent is required. Connect first or pass --agent.");
  }

  return { serviceUrl, sessionId, agentId };
}

async function handleServe(options, io) {
  const host = options.host ?? "127.0.0.1";
  const port = Number.parseInt(options.port ?? "4090", 10);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error(`Invalid port: ${options.port}`);
  }

  const dataDir = resolve(options.dataDir ?? ".session-hub");
  await listenSessionHubServer({ host, port, dataDir });
  write(io, "stdout", `Session Hub listening on http://${host}:${port}`);
}

async function handleConnect(positionals, options, io) {
  const sessionId = requireValue(positionals[0], "A session id is required.");
  const agentId = requireValue(options.agent, "--agent is required.");
  const dataDir = resolve(options.dataDir ?? ".session-hub");
  const store = createClientStateStore(dataDir);
  const { serviceUrl } = resolveClientContext(options, store.getClientState());
  const client = new SessionHubClient(serviceUrl);
  const result = await client.connect(sessionId, agentId);
  const state = store.setClientState({
    service_url: serviceUrl,
    session_id: sessionId,
    agent_id: agentId,
    connected_at: new Date().toISOString(),
  });

  if (options.json) {
    write(io, "stdout", JSON.stringify({ ...result, client_state: state }, null, 2));
    return;
  }

  write(io, "stdout", `Connected ${agentId} to session ${sessionId} at ${serviceUrl}`);
}

async function handleSend(options, io) {
  const dataDir = resolve(options.dataDir ?? ".session-hub");
  const store = createClientStateStore(dataDir);
  const state = store.getClientState();
  const { serviceUrl, sessionId, agentId } = resolveClientContext(options, state, {
    requireSession: true,
    requireAgent: true,
  });
  const body = requireValue(options.body, "--body is required.");
  const client = new SessionHubClient(serviceUrl);
  const result = await client.sendMessage(sessionId, agentId, body);

  if (options.json) {
    write(io, "stdout", JSON.stringify(result, null, 2));
    return;
  }

  write(io, "stdout", `Sent message to ${sessionId} as ${agentId}`);
}

async function handleRead(options, io) {
  const dataDir = resolve(options.dataDir ?? ".session-hub");
  const store = createClientStateStore(dataDir);
  const state = store.getClientState();
  const { serviceUrl, sessionId } = resolveClientContext(options, state, { requireSession: true });
  const limit = options.limit !== undefined ? Number.parseInt(options.limit, 10) : undefined;
  if (options.limit !== undefined && (!Number.isInteger(limit) || limit < 0)) {
    throw new Error(`Invalid limit: ${options.limit}`);
  }

  const client = new SessionHubClient(serviceUrl);
  const result = await client.listMessages(sessionId, { since: options.since, limit });

  if (options.json) {
    write(io, "stdout", JSON.stringify(result, null, 2));
    return;
  }

  write(io, "stdout", `Session: ${result.session.id}`);
  if (result.messages.length === 0) {
    write(io, "stdout", "No messages.");
    return;
  }

  for (const message of result.messages) {
    write(io, "stdout", `${message.created_at} ${message.agent_id}: ${message.body}`);
  }
}

export async function runCli(argv, io = { stdout: process.stdout, stderr: process.stderr }) {
  const [command, ...rest] = argv;

  if (!command || command === "--help" || command === "help") {
    write(io, "stdout", usage());
    return 0;
  }

  try {
    if (command === "serve") {
      const { options } = parseArgs(rest);
      await handleServe(options, io);
      return 0;
    }

    if (command === "connect") {
      const { positionals, options } = parseArgs(rest);
      await handleConnect(positionals, options, io);
      return 0;
    }

    if (command === "send") {
      const { options } = parseArgs(rest);
      await handleSend(options, io);
      return 0;
    }

    if (command === "read") {
      const { options } = parseArgs(rest);
      await handleRead(options, io);
      return 0;
    }

    throw new Error(`Unknown command: ${command}`);
  } catch (error) {
    write(io, "stderr", error instanceof Error ? error.message : String(error));
    return 1;
  }
}

export async function main(argv = process.argv.slice(2)) {
  const code = await runCli(argv);
  process.exitCode = code;
}
