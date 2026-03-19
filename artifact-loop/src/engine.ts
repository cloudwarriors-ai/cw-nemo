// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ArtifactLoopEngine — file-persisted coordination engine.
 *
 * Storage layout:
 *   <dataDir>/tasks/<id>.json              → Task
 *   <dataDir>/artifacts/<task-id>/<id>.json → NormalizedArtifact
 *   <dataDir>/state/<task-id>.json         → TaskState
 *   <dataDir>/derivations/<task-id>/<id>.json → DerivationRun
 */

import { mkdirSync, readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { derive } from "./derive.js";
import type {
  DerivationOutput,
  DerivationRun,
  IngestResult,
  NormalizedArtifact,
  NormalizationContext,
  Override,
  RawArtifact,
  SignalPayload,
  Task,
  TaskCreate,
  TaskState,
} from "./types.js";

export interface EngineOptions {
  dataDir: string;
}

const DEFAULT_STATE: TaskState = {
  status: "not_started",
  task_confidence: 0,
  binding_confidence: 0,
  missing_inputs: [],
};

export class ArtifactLoopEngine {
  readonly dataDir: string;
  private readonly tasksDir: string;
  private readonly artifactsDir: string;
  private readonly stateDir: string;
  private readonly derivationsDir: string;

  constructor(options: EngineOptions) {
    this.dataDir = options.dataDir;
    this.tasksDir = join(options.dataDir, "tasks");
    this.artifactsDir = join(options.dataDir, "artifacts");
    this.stateDir = join(options.dataDir, "state");
    this.derivationsDir = join(options.dataDir, "derivations");

    mkdirSync(this.tasksDir, { recursive: true });
    mkdirSync(this.artifactsDir, { recursive: true });
    mkdirSync(this.stateDir, { recursive: true });
    mkdirSync(this.derivationsDir, { recursive: true });
  }

  // ─── Task CRUD ────────────────────────────────────────────────────

  createTask(input: TaskCreate): Task {
    const existing = this.getTask(input.id);
    if (existing) {
      throw new Error(`Task already exists: ${input.id}`);
    }

    const task: Task = {
      ...input,
      last_activity_at: new Date().toISOString(),
    };

    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);
    this.writeJson(join(this.stateDir, `${task.id}.json`), {
      ...DEFAULT_STATE,
      status: input.status,
    });

    return task;
  }

  getTask(taskId: string): Task | undefined {
    return this.readJson<Task>(join(this.tasksDir, `${taskId}.json`));
  }

  // ─── State ────────────────────────────────────────────────────────

  getTaskState(taskId: string): TaskState | undefined {
    return this.readJson<TaskState>(join(this.stateDir, `${taskId}.json`));
  }

  // ─── Artifacts ────────────────────────────────────────────────────

  getArtifacts(taskId: string): NormalizedArtifact[] {
    const dir = join(this.artifactsDir, taskId);
    if (!existsSync(dir)) return [];

    return readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<NormalizedArtifact>(join(dir, f))!)
      .filter(Boolean);
  }

  // ─── Derivation History ───────────────────────────────────────────

  getDerivationHistory(taskId: string): DerivationRun[] {
    const dir = join(this.derivationsDir, taskId);
    if (!existsSync(dir)) return [];

    return readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => this.readJson<DerivationRun>(join(dir, f))!)
      .filter(Boolean)
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }

  // ─── Ingest ───────────────────────────────────────────────────────

  ingest(rawArtifact: RawArtifact, context: NormalizationContext): IngestResult {
    const task = this.getTask(context.primary_task_id);
    if (!task) {
      throw new Error(`Task not found: ${context.primary_task_id}`);
    }

    // Normalize raw artifact
    const normalizedArtifact: NormalizedArtifact = {
      id: `na-${rawArtifact.id}`,
      raw_artifact_id: rawArtifact.id,
      primary_task_id: context.primary_task_id,
      session_id: context.session_id,
      timestamp: rawArtifact.timestamp,
      normalization_state: "normalized",
      binding_confidence: context.context_source === "explicit_lock" ? 1.0 : 0.7,
      signal_payload: rawArtifact.raw_payload as SignalPayload,
    };

    // Store artifact
    const artifactDir = join(this.artifactsDir, context.primary_task_id);
    mkdirSync(artifactDir, { recursive: true });
    this.writeJson(join(artifactDir, `${normalizedArtifact.id}.json`), normalizedArtifact);

    // Load all artifacts for derivation
    const allArtifacts = this.getArtifacts(context.primary_task_id);
    const priorState = this.getTaskState(context.primary_task_id) ?? { ...DEFAULT_STATE };

    // Derive
    const derivationOutput = derive({
      priorState,
      normalizedArtifacts: allArtifacts,
      acceptanceSignals: task.acceptance_signals,
      override: task.override
        ? { id: `override-${task.id}`, ...task.override }
        : undefined,
    });

    // Fill task_id on derivation run
    if (derivationOutput.derivationRun) {
      derivationOutput.derivationRun.task_id = context.primary_task_id;
    }

    // Persist state
    this.writeJson(
      join(this.stateDir, `${context.primary_task_id}.json`),
      derivationOutput.nextState,
    );

    // Persist derivation run
    if (derivationOutput.derivationRun) {
      const runDir = join(this.derivationsDir, context.primary_task_id);
      mkdirSync(runDir, { recursive: true });
      this.writeJson(
        join(runDir, `${derivationOutput.derivationRun.id}.json`),
        derivationOutput.derivationRun,
      );
    }

    // Update task activity
    task.last_activity_at = rawArtifact.timestamp;
    task.status = derivationOutput.nextState.status;
    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);

    return { normalizedArtifact, derivationOutput };
  }

  // ─── Override ─────────────────────────────────────────────────────

  applyOverride(taskId: string, override: Override): DerivationOutput {
    const task = this.getTask(taskId);
    if (!task) {
      throw new Error(`Task not found: ${taskId}`);
    }

    // Store override on task
    task.override = override;
    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);

    // Run derivation with override
    const allArtifacts = this.getArtifacts(taskId);
    const priorState = this.getTaskState(taskId) ?? { ...DEFAULT_STATE };

    const overrideRecord = {
      id: `override-${taskId}-${Date.now()}`,
      ...override,
    };

    const derivationOutput = derive({
      priorState,
      normalizedArtifacts: allArtifacts,
      acceptanceSignals: task.acceptance_signals,
      override: overrideRecord,
    });

    // Fill task_id
    if (derivationOutput.derivationRun) {
      derivationOutput.derivationRun.task_id = taskId;
    }

    // Persist state
    this.writeJson(join(this.stateDir, `${taskId}.json`), derivationOutput.nextState);

    // Persist derivation run
    if (derivationOutput.derivationRun) {
      const runDir = join(this.derivationsDir, taskId);
      mkdirSync(runDir, { recursive: true });
      this.writeJson(
        join(runDir, `${derivationOutput.derivationRun.id}.json`),
        derivationOutput.derivationRun,
      );
    }

    // Update task status
    task.status = derivationOutput.nextState.status;
    task.last_activity_at = override.timestamp;
    this.writeJson(join(this.tasksDir, `${task.id}.json`), task);

    return derivationOutput;
  }

  // ─── File I/O ─────────────────────────────────────────────────────

  private writeJson(path: string, data: unknown): void {
    writeFileSync(path, JSON.stringify(data, null, 2) + "\n", "utf-8");
  }

  private readJson<T>(path: string): T | undefined {
    if (!existsSync(path)) return undefined;
    return JSON.parse(readFileSync(path, "utf-8")) as T;
  }
}

export function createEngine(options: EngineOptions): ArtifactLoopEngine {
  return new ArtifactLoopEngine(options);
}
