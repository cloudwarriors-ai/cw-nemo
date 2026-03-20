// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createSessionHubServer } from "../src/server.js";

async function listen(server) {
  await new Promise((resolve) => {
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return `http://127.0.0.1:${address.port}`;
}

async function requestJson(baseUrl, path, init) {
  const response = await fetch(`${baseUrl}${path}`, init);
  const body = await response.json();
  return { response, body };
}

test("service connects agents and persists messages by session", async () => {
  const dataDir = mkdtempSync(join(tmpdir(), "session-hub-service-"));
  const server = createSessionHubServer({ dataDir });
  const baseUrl = await listen(server);

  try {
    const health = await requestJson(baseUrl, "/health");
    assert.equal(health.response.status, 200);
    assert.equal(health.body.ok, true);

    const firstConnect = await requestJson(baseUrl, "/sessions/demo/connect", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ agent_id: "alpha" }),
    });
    assert.equal(firstConnect.response.status, 200);
    assert.equal(firstConnect.body.session.id, "demo");
    assert.equal(firstConnect.body.session.agents.length, 1);

    const secondConnect = await requestJson(baseUrl, "/sessions/demo/connect", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ agent_id: "alpha" }),
    });
    assert.equal(secondConnect.body.session.agents.length, 1);

    const emptyRead = await requestJson(baseUrl, "/sessions/demo/messages");
    assert.equal(emptyRead.response.status, 200);
    assert.deepEqual(emptyRead.body.messages, []);

    const send = await requestJson(baseUrl, "/sessions/demo/messages", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ agent_id: "alpha", body: "hello from alpha" }),
    });
    assert.equal(send.response.status, 201);
    assert.equal(send.body.message.session_id, "demo");
    assert.equal(send.body.message.agent_id, "alpha");

    const read = await requestJson(baseUrl, "/sessions/demo/messages");
    assert.equal(read.response.status, 200);
    assert.equal(read.body.messages.length, 1);
    assert.equal(read.body.messages[0].body, "hello from alpha");
  } finally {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
    rmSync(dataDir, { recursive: true, force: true });
  }
});
