// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createSessionHubServer } from "../src/server.js";
import { runCli } from "../src/cli.js";

async function listen(server) {
  await new Promise((resolve) => {
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return `http://127.0.0.1:${address.port}`;
}

function makeIo() {
  let stdout = "";
  let stderr = "";
  return {
    io: {
      stdout: {
        write(chunk) {
          stdout += String(chunk);
        },
      },
      stderr: {
        write(chunk) {
          stderr += String(chunk);
        },
      },
    },
    getStdout() {
      return stdout;
    },
    getStderr() {
      return stderr;
    },
  };
}

test("cli connect/send/read uses persisted client state", async () => {
  const serviceDataDir = mkdtempSync(join(tmpdir(), "session-hub-cli-service-"));
  const clientDataDir = mkdtempSync(join(tmpdir(), "session-hub-cli-client-"));
  const server = createSessionHubServer({ dataDir: serviceDataDir });
  const baseUrl = await listen(server);

  try {
    const connectIo = makeIo();
    const connectCode = await runCli([
      "connect",
      "demo",
      "--agent",
      "alpha",
      "--service-url",
      baseUrl,
      "--data-dir",
      clientDataDir,
    ], connectIo.io);
    assert.equal(connectCode, 0);
    assert.match(connectIo.getStdout(), /Connected alpha to session demo/);

    const state = JSON.parse(readFileSync(join(clientDataDir, "state", "client.json"), "utf8"));
    assert.equal(state.session_id, "demo");
    assert.equal(state.agent_id, "alpha");
    assert.equal(state.service_url, baseUrl);

    const sendIo = makeIo();
    const sendCode = await runCli([
      "send",
      "--body",
      "hello from alpha",
      "--data-dir",
      clientDataDir,
    ], sendIo.io);
    assert.equal(sendCode, 0);
    assert.match(sendIo.getStdout(), /Sent message to demo as alpha/);

    const readIo = makeIo();
    const readCode = await runCli([
      "read",
      "--data-dir",
      clientDataDir,
    ], readIo.io);
    assert.equal(readCode, 0);
    assert.match(readIo.getStdout(), /Session: demo/);
    assert.match(readIo.getStdout(), /alpha: hello from alpha/);

    const jsonIo = makeIo();
    const jsonCode = await runCli([
      "read",
      "--data-dir",
      clientDataDir,
      "--json",
    ], jsonIo.io);
    assert.equal(jsonCode, 0);
    const parsed = JSON.parse(jsonIo.getStdout());
    assert.equal(parsed.session.id, "demo");
    assert.equal(parsed.messages.length, 1);
    assert.equal(parsed.messages[0].body, "hello from alpha");
  } finally {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
    rmSync(serviceDataDir, { recursive: true, force: true });
    rmSync(clientDataDir, { recursive: true, force: true });
  }
});
