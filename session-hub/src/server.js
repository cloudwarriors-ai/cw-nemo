// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { createServer } from "node:http";
import { SessionHubError, SessionHubStore } from "./store.js";

function sendJson(res, statusCode, body) {
  res.writeHead(statusCode, { "content-type": "application/json; charset=utf-8" });
  res.end(`${JSON.stringify(body, null, 2)}\n`);
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw.trim()) {
    throw new SessionHubError("Request body is required", 400);
  }
  try {
    return JSON.parse(raw);
  } catch {
    throw new SessionHubError("Request body must be valid JSON", 400);
  }
}

function splitPath(url) {
  return url.pathname.split("/").filter(Boolean);
}

export function createSessionHubServer({ dataDir }) {
  const store = new SessionHubStore(dataDir);

  return createServer(async (req, res) => {
    try {
      if (!req.url || !req.method) {
        throw new SessionHubError("Request is missing URL or method", 400);
      }

      const url = new URL(req.url, "http://session-hub.local");
      const path = splitPath(url);

      if (req.method === "GET" && path.length === 1 && path[0] === "health") {
        sendJson(res, 200, { ok: true, service: "session-hub", data_dir: store.dataDir });
        return;
      }

      if (path.length === 2 && path[0] === "sessions") {
        const sessionId = decodeURIComponent(path[1]);
        if (req.method === "GET") {
          const session = store.getSession(sessionId);
          if (!session) {
            throw new SessionHubError(`Session not found: ${sessionId}`, 404);
          }
          sendJson(res, 200, { session });
          return;
        }
      }

      if (path.length === 3 && path[0] === "sessions" && path[2] === "connect") {
        const sessionId = decodeURIComponent(path[1]);
        if (req.method !== "PUT") {
          throw new SessionHubError("Method not allowed", 405);
        }
        const body = await readJsonBody(req);
        const agentId = String(body.agent_id ?? "").trim();
        if (!agentId) {
          throw new SessionHubError("agent_id is required", 400);
        }
        const session = store.connectSession(sessionId, agentId);
        sendJson(res, 200, { session });
        return;
      }

      if (path.length === 3 && path[0] === "sessions" && path[2] === "messages") {
        const sessionId = decodeURIComponent(path[1]);
        if (req.method === "GET") {
          const since = url.searchParams.get("since") ?? undefined;
          const limitValue = url.searchParams.get("limit");
          const limit = limitValue ? Number.parseInt(limitValue, 10) : undefined;
          if (limitValue && (!Number.isInteger(limit) || limit < 0)) {
            throw new SessionHubError(`Invalid limit: ${limitValue}`, 400);
          }
          sendJson(res, 200, store.listMessages(sessionId, { since, limit }));
          return;
        }

        if (req.method === "POST") {
          const body = await readJsonBody(req);
          const agentId = String(body.agent_id ?? "").trim();
          const text = String(body.body ?? "").trim();
          if (!agentId) {
            throw new SessionHubError("agent_id is required", 400);
          }
          const result = store.createMessage(sessionId, agentId, text);
          sendJson(res, 201, result);
          return;
        }
      }

      throw new SessionHubError("Not found", 404);
    } catch (error) {
      const statusCode = error instanceof SessionHubError ? error.statusCode : 500;
      const message = error instanceof Error ? error.message : "Internal server error";
      sendJson(res, statusCode, { error: message });
    }
  });
}

export async function listenSessionHubServer({ host, port, dataDir }) {
  const server = createSessionHubServer({ dataDir });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      server.off("error", reject);
      resolve();
    });
  });
  return server;
}
