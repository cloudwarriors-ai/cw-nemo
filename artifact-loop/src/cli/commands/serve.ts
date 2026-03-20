// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Command } from "commander";
import { resolve } from "node:path";
import { listenArtifactLoopServer } from "../../service/server.js";

export function registerServe(program: Command): void {
  program
    .command("serve")
    .description("Start the Artifact Loop shared coordination service")
    .option("--host <host>", "Host to bind", "127.0.0.1")
    .option("--port <port>", "Port to bind", "4080")
    .option("--data-dir <dir>", "Data directory")
    .action(async (opts: { host?: string; port?: string; dataDir?: string }) => {
      const port = Number.parseInt(opts.port ?? "4080", 10);
      if (!Number.isInteger(port) || port < 0 || port > 65535) {
        console.error(`Invalid port: ${opts.port}`);
        process.exitCode = 1;
        return;
      }

      const host = opts.host ?? "127.0.0.1";
      const dataDir = resolve(opts.dataDir ?? ".artifact-loop");

      try {
        await listenArtifactLoopServer({
          host,
          port,
          dataDir,
        });
        console.log(`Artifact Loop service listening on http://${host}:${port}`);
      } catch (err) {
        console.error((err as Error).message);
        process.exitCode = 1;
      }
    });
}
