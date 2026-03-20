// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const scriptPath = resolve(process.cwd(), "scripts/scenarios/tailscale_shared_coordination_v1.sh");

describe("tailscale shared coordination scenario", () => {
  it("requires an external service url and supports validate-only argument checks", () => {
    const missingEnv = spawnSync("bash", [scriptPath], {
      cwd: process.cwd(),
      env: {
        ...process.env,
        ARTIFACT_LOOP_SERVICE_URL: "",
        ARTIFACT_LOOP_TAILSCALE_VALIDATE_ONLY: "1",
      },
      encoding: "utf8",
    });
    expect(missingEnv.status).not.toBe(0);
    expect(missingEnv.stderr).toContain("ARTIFACT_LOOP_SERVICE_URL is required");

    const validateOnly = spawnSync("bash", [scriptPath], {
      cwd: process.cwd(),
      env: {
        ...process.env,
        ARTIFACT_LOOP_SERVICE_URL: "https://nemoclaw.tailcc6c5f.ts.net:4443",
        ARTIFACT_LOOP_HUB_URL: "https://nemoclaw.tailcc6c5f.ts.net:4443",
        ARTIFACT_LOOP_TAILSCALE_VALIDATE_ONLY: "1",
        ARTIFACT_LOOP_TAILSCALE_RUN_ID: "test-run",
      },
      encoding: "utf8",
    });
    expect(validateOnly.status).toBe(0);
    expect(validateOnly.stdout).toContain("PASS tailscale_shared_coordination_v1_args");
    expect(validateOnly.stdout).toContain("service_url: https://nemoclaw.tailcc6c5f.ts.net:4443");
    expect(validateOnly.stdout).toContain("project_id: proj-tailnet-test-run");
  });
});
