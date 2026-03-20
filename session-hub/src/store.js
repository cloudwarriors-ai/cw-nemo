// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { join, resolve } from "node:path";

export class SessionHubError extends Error {
  constructor(message, statusCode = 400) {
    super(message);
    this.statusCode = statusCode;
  }
}

function safeId(value) {
  return encodeURIComponent(value);
}

function readJson(path) {
  if (!existsSync(path)) {
    return undefined;
  }
  return JSON.parse(readFileSync(path, "utf8"));
}

function writeJson(path, value) {
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

export class SessionHubStore {
  constructor(dataDir) {
    this.dataDir = resolve(dataDir);
    this.sessionsDir = join(this.dataDir, "sessions");
    this.messagesDir = join(this.dataDir, "messages");
    this.stateDir = join(this.dataDir, "state");

    mkdirSync(this.sessionsDir, { recursive: true });
    mkdirSync(this.messagesDir, { recursive: true });
    mkdirSync(this.stateDir, { recursive: true });
  }

  sessionPath(sessionId) {
    return join(this.sessionsDir, `${safeId(sessionId)}.json`);
  }

  sessionMessagesDir(sessionId) {
    return join(this.messagesDir, safeId(sessionId));
  }

  clientStatePath() {
    return join(this.stateDir, "client.json");
  }

  getSession(sessionId) {
    return readJson(this.sessionPath(sessionId));
  }

  connectSession(sessionId, agentId) {
    const now = new Date().toISOString();
    const existing = this.getSession(sessionId);
    const session = existing ?? {
      id: sessionId,
      created_at: now,
      updated_at: now,
      agents: [],
    };

    const agent = session.agents.find((item) => item.agent_id === agentId);
    if (agent) {
      agent.last_seen_at = now;
    } else {
      session.agents.push({
        agent_id: agentId,
        connected_at: now,
        last_seen_at: now,
      });
    }
    session.updated_at = now;
    writeJson(this.sessionPath(sessionId), session);
    return session;
  }

  touchSessionAgent(sessionId, agentId) {
    const session = this.getSession(sessionId);
    if (!session) {
      throw new SessionHubError(`Session not found: ${sessionId}`, 404);
    }
    return this.connectSession(sessionId, agentId);
  }

  createMessage(sessionId, agentId, body) {
    if (!body || !body.trim()) {
      throw new SessionHubError("Message body is required", 400);
    }

    const now = new Date().toISOString();
    const session = this.touchSessionAgent(sessionId, agentId);
    const message = {
      id: `msg-${Date.now()}-${randomUUID()}`,
      session_id: sessionId,
      agent_id: agentId,
      body: body.trim(),
      created_at: now,
    };

    const dir = this.sessionMessagesDir(sessionId);
    mkdirSync(dir, { recursive: true });
    writeJson(join(dir, `${safeId(message.id)}.json`), message);
    return { session, message };
  }

  listMessages(sessionId, options = {}) {
    const session = this.getSession(sessionId);
    if (!session) {
      throw new SessionHubError(`Session not found: ${sessionId}`, 404);
    }

    const dir = this.sessionMessagesDir(sessionId);
    if (!existsSync(dir)) {
      return { session, messages: [] };
    }

    const since = options.since ? new Date(options.since).getTime() : undefined;
    if (options.since && Number.isNaN(since)) {
      throw new SessionHubError(`Invalid since timestamp: ${options.since}`, 400);
    }

    let messages = readdirSync(dir)
      .filter((entry) => entry.endsWith(".json"))
      .map((entry) => readJson(join(dir, entry)))
      .filter(Boolean)
      .sort((a, b) => a.created_at.localeCompare(b.created_at));

    if (since !== undefined) {
      messages = messages.filter((message) => new Date(message.created_at).getTime() > since);
    }

    if (options.limit !== undefined) {
      messages = messages.slice(-options.limit);
    }

    return { session, messages };
  }

  getClientState() {
    return readJson(this.clientStatePath());
  }

  setClientState(state) {
    writeJson(this.clientStatePath(), state);
    return state;
  }
}
