// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { resolve } from "node:path";
import { SessionHubStore } from "./store.js";

const DEFAULT_REMOTE_TIMEOUT_MS = 10_000;

export class RemoteSessionHubError extends Error {
  constructor(serviceUrl, path, message, statusCode) {
    super(message);
    this.serviceUrl = serviceUrl;
    this.path = path;
    this.statusCode = statusCode;
  }
}

function normalizeServiceUrl(url) {
  return url.replace(/\/+$/, "");
}

async function parseJsonResponse(response, serviceUrl, path) {
  const text = await response.text();
  if (!text.trim()) {
    throw new RemoteSessionHubError(serviceUrl, path, `Remote service ${serviceUrl}: empty response from ${path}`, response.status);
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new RemoteSessionHubError(serviceUrl, path, `Remote service ${serviceUrl}: invalid JSON response from ${path}`, response.status);
  }
}

export class SessionHubClient {
  constructor(serviceUrl) {
    this.serviceUrl = normalizeServiceUrl(serviceUrl);
  }

  async request(path, init) {
    const url = `${this.serviceUrl}${path}`;
    let response;
    try {
      response = await fetch(url, {
        ...init,
        signal: AbortSignal.timeout(DEFAULT_REMOTE_TIMEOUT_MS),
      });
    } catch (error) {
      throw new RemoteSessionHubError(
        this.serviceUrl,
        path,
        `Remote service ${this.serviceUrl}: request failed for ${path} (${error.message})`,
      );
    }

    const parsed = await parseJsonResponse(response, this.serviceUrl, path);
    if (!response.ok) {
      throw new RemoteSessionHubError(
        this.serviceUrl,
        path,
        `Remote service ${this.serviceUrl}: ${parsed.error ?? `${response.status} ${response.statusText}`}`,
        response.status,
      );
    }
    return parsed;
  }

  health() {
    return this.request("/health");
  }

  getSession(sessionId) {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}`);
  }

  connect(sessionId, agentId) {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/connect`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ agent_id: agentId }),
    });
  }

  sendMessage(sessionId, agentId, body) {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ agent_id: agentId, body }),
    });
  }

  listMessages(sessionId, options = {}) {
    const url = new URL(`/sessions/${encodeURIComponent(sessionId)}/messages`, "http://session-hub.local");
    if (options.since) {
      url.searchParams.set("since", options.since);
    }
    if (options.limit !== undefined) {
      url.searchParams.set("limit", String(options.limit));
    }
    return this.request(`${url.pathname}${url.search}`);
  }
}

export function createClientStateStore(dataDir) {
  return new SessionHubStore(resolve(dataDir ?? ".session-hub"));
}

export function resolveServiceUrl(explicit, state) {
  return explicit ?? state?.service_url ?? process.env.SESSION_HUB_SERVICE_URL;
}
