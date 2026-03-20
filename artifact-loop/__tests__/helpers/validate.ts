// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import Ajv, { type ErrorObject } from "ajv";
import addFormats from "ajv-formats";
import { readFileSync, readdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { expect } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const CONTRACTS_DIR = resolve(__dirname, "../../contracts");

let ajvInstance: Ajv | null = null;

function getAjv(): Ajv {
  if (ajvInstance) return ajvInstance;

  const ajv = new Ajv({ allErrors: true, strict: true });
  addFormats(ajv);

  // Pre-load all schemas so cross-schema $refs resolve
  const schemaFiles = readdirSync(CONTRACTS_DIR).filter((f) =>
    f.endsWith(".schema.json"),
  );
  for (const file of schemaFiles) {
    const schema = JSON.parse(
      readFileSync(resolve(CONTRACTS_DIR, file), "utf-8"),
    );
    ajv.addSchema(schema);
  }

  ajvInstance = ajv;
  return ajv;
}

function loadSchema(schemaName: string): object {
  const path = resolve(CONTRACTS_DIR, schemaName);
  return JSON.parse(readFileSync(path, "utf-8"));
}

export function getValidator(schemaName: string) {
  const ajv = getAjv();
  // Return cached validator if schema was already compiled
  const existing = ajv.getSchema(schemaName);
  if (existing) return existing;
  const schema = loadSchema(schemaName);
  return ajv.compile(schema);
}

export function assertValid(schemaName: string, data: unknown): void {
  const validate = getValidator(schemaName);
  const valid = validate(data);
  if (!valid) {
    const errors = validate.errors
      ?.map((e: ErrorObject) => `${e.instancePath} ${e.message}`)
      .join("\n");
    expect.unreachable(
      `Expected valid but got errors:\n${errors}\nData: ${JSON.stringify(data, null, 2)}`,
    );
  }
}

export function assertInvalid(schemaName: string, data: unknown): void {
  const validate = getValidator(schemaName);
  const valid = validate(data);
  expect(valid).toBe(false);
}

/** Reset ajv instance — call between tests if schemas change */
export function resetValidator(): void {
  ajvInstance = null;
}
