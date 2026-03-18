import { writeFile } from "fs/promises";
import { join, dirname } from "path";
import { spawn } from "child_process";
import { existsSync, mkdirSync, writeFileSync } from "fs";
const DEFAULT_WORKER_PORT = 37777;
const CLAUDE_MEM_DATA_DIR = "/root/.claude-mem";
// ============================================================================
// Worker HTTP Client
// ============================================================================
function workerBaseUrl(port) {
    return `http://127.0.0.1:${port}`;
}
async function workerPost(port, path, body, logger) {
    try {
        const response = await fetch(`${workerBaseUrl(port)}${path}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            logger.warn(`[claude-mem] Worker POST ${path} returned ${response.status}`);
            return null;
        }
        return (await response.json());
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        logger.warn(`[claude-mem] Worker POST ${path} failed: ${message}`);
        return null;
    }
}
function workerPostFireAndForget(port, path, body, logger) {
    fetch(`${workerBaseUrl(port)}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    }).catch((error) => {
        const message = error instanceof Error ? error.message : String(error);
        logger.warn(`[claude-mem] Worker POST ${path} failed: ${message}`);
    });
}
async function workerGetText(port, path, logger) {
    try {
        const response = await fetch(`${workerBaseUrl(port)}${path}`);
        if (!response.ok) {
            logger.warn(`[claude-mem] Worker GET ${path} returned ${response.status}`);
            return null;
        }
        return await response.text();
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        logger.warn(`[claude-mem] Worker GET ${path} failed: ${message}`);
        return null;
    }
}
// ============================================================================
// Worker Process Management
// ============================================================================
let workerProcess = null;
function ensureDataDir() {
    if (!existsSync(CLAUDE_MEM_DATA_DIR)) {
        mkdirSync(CLAUDE_MEM_DATA_DIR, { recursive: true });
    }
    const logsDir = join(CLAUDE_MEM_DATA_DIR, "logs");
    if (!existsSync(logsDir)) {
        mkdirSync(logsDir, { recursive: true });
    }
}
function ensureSettings(port) {
    const settingsPath = join(CLAUDE_MEM_DATA_DIR, "settings.json");
    if (!existsSync(settingsPath)) {
        const settings = {
            workerPort: port,
            dataDir: CLAUDE_MEM_DATA_DIR,
            logLevel: "info",
        };
        writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
    }
}
async function startWorker(port, logger) {
    // Find the worker binary relative to this extension
    const workerPath = join(dirname(new URL(import.meta.url).pathname), "..", "worker", "worker-service.cjs");
    if (!existsSync(workerPath)) {
        logger.error(`[claude-mem] Worker binary not found at ${workerPath}`);
        return false;
    }
    ensureDataDir();
    ensureSettings(port);
    // Use full path to bun — PATH may not include /root/.bun/bin inside Docker
    const bunBin = existsSync("/root/.bun/bin/bun") ? "/root/.bun/bin/bun" : "bun";
    logger.info(`[claude-mem] Starting worker: ${bunBin} ${workerPath} start`);
    workerProcess = spawn(bunBin, [workerPath, "start"], {
        env: {
            ...process.env,
            CLAUDE_MEM_DATA_DIR: CLAUDE_MEM_DATA_DIR,
            CLAUDE_MEM_WORKER_PORT: String(port),
            CLAUDE_MEM_WORKER_HOST: "0.0.0.0",
            // Point to external Chroma container instead of spawning local
            CLAUDE_MEM_CHROMA_MODE: "external",
            CLAUDE_MEM_CHROMA_HOST: "claude-mem-chroma",
            CLAUDE_MEM_CHROMA_PORT: "8000",
            // Ensure OpenRouter provider config is set
            CLAUDE_MEM_PROVIDER: "openrouter",
            CLAUDE_MEM_OPENROUTER_MODEL: "anthropic/claude-sonnet-4-5",
            CLAUDE_MEM_OPENROUTER_APP_NAME: "moltbot-claude-mem",
            // Pass through the OpenRouter API key from gateway env
            CLAUDE_MEM_OPENROUTER_API_KEY: process.env.OPENROUTER_API_KEY || "",
        },
        stdio: ["ignore", "pipe", "pipe"],
        detached: false,
    });
    workerProcess.stdout?.on("data", (data) => {
        const line = data.toString().trim();
        if (line)
            logger.info(`[claude-mem:worker] ${line}`);
    });
    workerProcess.stderr?.on("data", (data) => {
        const line = data.toString().trim();
        if (line)
            logger.warn(`[claude-mem:worker] ${line}`);
    });
    workerProcess.on("exit", (code) => {
        logger.warn(`[claude-mem] Worker process exited with code ${code}`);
        workerProcess = null;
    });
    // Wait for worker to become healthy (up to 15 seconds)
    for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 500));
        try {
            const res = await fetch(`${workerBaseUrl(port)}/api/health`);
            if (res.ok) {
                logger.info(`[claude-mem] Worker is healthy on port ${port}`);
                return true;
            }
        }
        catch {
            // Worker not ready yet
        }
    }
    logger.error("[claude-mem] Worker failed to start within 15 seconds");
    return false;
}
function stopWorker(logger) {
    if (workerProcess) {
        logger.info("[claude-mem] Stopping worker process");
        workerProcess.kill("SIGTERM");
        workerProcess = null;
    }
}
// ============================================================================
// Plugin Entry Point
// ============================================================================
export default function claudeMemPlugin(api) {
    const userConfig = (api.pluginConfig || {});
    const workerPort = userConfig.workerPort || DEFAULT_WORKER_PORT;
    const baseProjectName = userConfig.project || "openclaw";
    function getProjectName(ctx) {
        if (ctx.agentId)
            return `openclaw-${ctx.agentId}`;
        return baseProjectName;
    }
    // Session tracking
    const sessionIds = new Map();
    const workspaceDirsBySessionKey = new Map();
    const syncMemoryFile = userConfig.syncMemoryFile !== false;
    function getContentSessionId(sessionKey) {
        const key = sessionKey || "default";
        if (!sessionIds.has(key)) {
            sessionIds.set(key, `openclaw-${key}-${Date.now()}`);
        }
        return sessionIds.get(key);
    }
    async function syncMemoryToWorkspace(workspaceDir, ctx) {
        const projects = [baseProjectName];
        const agentProject = ctx ? getProjectName(ctx) : null;
        if (agentProject && agentProject !== baseProjectName) {
            projects.push(agentProject);
        }
        const contextText = await workerGetText(workerPort, `/api/context/inject?projects=${encodeURIComponent(projects.join(","))}`, api.logger);
        if (contextText && contextText.trim().length > 0) {
            try {
                await writeFile(join(workspaceDir, "MEMORY.md"), contextText, "utf-8");
                api.logger.info(`[claude-mem] MEMORY.md synced to ${workspaceDir}`);
            }
            catch (writeError) {
                const msg = writeError instanceof Error ? writeError.message : String(writeError);
                api.logger.warn(`[claude-mem] Failed to write MEMORY.md: ${msg}`);
            }
        }
    }
    // ------------------------------------------------------------------
    // Service: Worker process lifecycle
    // ------------------------------------------------------------------
    api.registerService({
        id: "claude-mem-worker",
        start: async () => {
            const started = await startWorker(workerPort, api.logger);
            if (!started) {
                api.logger.error("[claude-mem] Worker failed to start — plugin will operate in degraded mode");
            }
        },
        stop: async () => {
            stopWorker(api.logger);
        },
    });
    // ------------------------------------------------------------------
    // Event: session_start
    // ------------------------------------------------------------------
    api.on("session_start", async (_event, ctx) => {
        const contentSessionId = getContentSessionId(ctx.sessionKey);
        await workerPost(workerPort, "/api/sessions/init", {
            contentSessionId,
            project: getProjectName(ctx),
            prompt: "",
        }, api.logger);
        api.logger.info(`[claude-mem] Session initialized: ${contentSessionId}`);
    });
    // ------------------------------------------------------------------
    // Event: message_received
    // ------------------------------------------------------------------
    api.on("message_received", async (event, ctx) => {
        const sessionKey = ctx.conversationId || ctx.channelId || "default";
        const contentSessionId = getContentSessionId(sessionKey);
        await workerPost(workerPort, "/api/sessions/init", {
            contentSessionId,
            project: baseProjectName,
            prompt: event.content || "[media prompt]",
        }, api.logger);
    });
    // ------------------------------------------------------------------
    // Event: after_compaction
    // ------------------------------------------------------------------
    api.on("after_compaction", async (_event, ctx) => {
        const contentSessionId = getContentSessionId(ctx.sessionKey);
        await workerPost(workerPort, "/api/sessions/init", {
            contentSessionId,
            project: getProjectName(ctx),
            prompt: "",
        }, api.logger);
        api.logger.info(`[claude-mem] Session re-initialized after compaction: ${contentSessionId}`);
    });
    // ------------------------------------------------------------------
    // Event: before_agent_start
    // ------------------------------------------------------------------
    api.on("before_agent_start", async (event, ctx) => {
        if (ctx.workspaceDir) {
            workspaceDirsBySessionKey.set(ctx.sessionKey || "default", ctx.workspaceDir);
        }
        const contentSessionId = getContentSessionId(ctx.sessionKey);
        await workerPost(workerPort, "/api/sessions/init", {
            contentSessionId,
            project: getProjectName(ctx),
            prompt: event.prompt || "agent run",
        }, api.logger);
        if (syncMemoryFile && ctx.workspaceDir) {
            await syncMemoryToWorkspace(ctx.workspaceDir, ctx);
        }
    });
    // ------------------------------------------------------------------
    // Event: tool_result_persist
    // ------------------------------------------------------------------
    api.on("tool_result_persist", (event, ctx) => {
        const toolName = event.toolName;
        if (!toolName)
            return;
        const contentSessionId = getContentSessionId(ctx.sessionKey);
        let toolResponseText = "";
        const content = event.message?.content;
        if (Array.isArray(content)) {
            toolResponseText = content
                .filter((block) => (block.type === "tool_result" || block.type === "text") && "text" in block)
                .map((block) => String(block.text))
                .join("\n");
        }
        workerPostFireAndForget(workerPort, "/api/sessions/observations", {
            contentSessionId,
            tool_name: toolName,
            tool_input: event.params || {},
            tool_response: toolResponseText,
            cwd: "",
        }, api.logger);
        const workspaceDir = ctx.workspaceDir || workspaceDirsBySessionKey.get(ctx.sessionKey || "default");
        if (syncMemoryFile && workspaceDir) {
            syncMemoryToWorkspace(workspaceDir, ctx);
        }
    });
    // ------------------------------------------------------------------
    // Event: agent_end
    // ------------------------------------------------------------------
    api.on("agent_end", async (event, ctx) => {
        const contentSessionId = getContentSessionId(ctx.sessionKey);
        let lastAssistantMessage = "";
        if (Array.isArray(event.messages)) {
            for (let i = event.messages.length - 1; i >= 0; i--) {
                const message = event.messages[i];
                if (message?.role === "assistant") {
                    if (typeof message.content === "string") {
                        lastAssistantMessage = message.content;
                    }
                    else if (Array.isArray(message.content)) {
                        lastAssistantMessage = message.content
                            .filter((block) => block.type === "text")
                            .map((block) => block.text || "")
                            .join("\n");
                    }
                    break;
                }
            }
        }
        await workerPost(workerPort, "/api/sessions/summarize", {
            contentSessionId,
            last_assistant_message: lastAssistantMessage,
        }, api.logger);
        workerPostFireAndForget(workerPort, "/api/sessions/complete", {
            contentSessionId,
        }, api.logger);
    });
    // ------------------------------------------------------------------
    // Event: session_end
    // ------------------------------------------------------------------
    api.on("session_end", async (_event, ctx) => {
        const key = ctx.sessionKey || "default";
        sessionIds.delete(key);
        workspaceDirsBySessionKey.delete(key);
    });
    // ------------------------------------------------------------------
    // Event: gateway_start
    // ------------------------------------------------------------------
    api.on("gateway_start", async () => {
        workspaceDirsBySessionKey.clear();
        sessionIds.clear();
        api.logger.info("[claude-mem] Gateway started — session tracking reset");
    });
    // ------------------------------------------------------------------
    // Command: /claude-mem-status
    // ------------------------------------------------------------------
    api.registerCommand({
        name: "claude-mem-status",
        description: "Check Claude-Mem worker health and session status",
        handler: async () => {
            const healthText = await workerGetText(workerPort, "/api/health", api.logger);
            if (!healthText) {
                return `Claude-Mem worker unreachable at port ${workerPort}`;
            }
            try {
                const health = JSON.parse(healthText);
                return [
                    "Claude-Mem Worker Status",
                    `Status: ${health.status || "unknown"}`,
                    `Port: ${workerPort}`,
                    `Active sessions: ${sessionIds.size}`,
                    `Worker PID: ${workerProcess?.pid || "unknown"}`,
                ].join("\n");
            }
            catch {
                return "Claude-Mem worker responded but returned unexpected data";
            }
        },
    });
    // ------------------------------------------------------------------
    // Tools: memory save exposed to agents (memory_search removed — using built-in)
    // ------------------------------------------------------------------
    api.registerTool({
        name: "memory_save",
        label: "Save Memory",
        description: "Manually save an important observation, decision, or fact to persistent memory. " +
            "Use this when you learn something important that should be remembered across sessions.",
        parameters: {
            type: "object",
            properties: {
                text: { type: "string", description: "The information to save" },
                title: { type: "string", description: "Short title for the memory" },
                type: { type: "string", description: "Type: bugfix, feature, refactor, discovery, decision, change" },
            },
            required: ["text"],
        },
        execute: async (_toolCallId, params) => {
            const text = String(params.text || "");
            const title = params.title ? String(params.title) : undefined;
            const type = params.type ? String(params.type) : "discovery";
            const result = await workerPost(workerPort, "/api/memory/save", {
                text,
                title,
                type,
                project: baseProjectName,
            }, api.logger);
            if (result) {
                return { content: [{ type: "text", text: `Memory saved: ${title || "(untitled)"}` }] };
            }
            return { content: [{ type: "text", text: "Failed to save memory — worker may be unavailable." }] };
        },
    });
    api.registerTool({
        name: "memory_get_observations",
        label: "Get Observations",
        description: "Fetch full observation details by IDs. Use after memory_search to get complete details " +
            "for specific observations. Always batch multiple IDs in a single call.",
        parameters: {
            type: "object",
            properties: {
                ids: {
                    type: "array",
                    items: { type: "number" },
                    description: "Array of observation IDs to fetch (from memory_search results)",
                },
            },
            required: ["ids"],
        },
        execute: async (_toolCallId, params) => {
            const ids = Array.isArray(params.ids) ? params.ids.map(Number) : [];
            if (ids.length === 0) {
                return { content: [{ type: "text", text: "No observation IDs provided." }] };
            }
            const result = await workerPost(workerPort, "/api/observations/batch", { ids }, api.logger);
            if (result) {
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            return { content: [{ type: "text", text: "Failed to fetch observations — worker may be unavailable." }] };
        },
    });
    api.registerTool({
        name: "memory_timeline",
        label: "Memory Timeline",
        description: "Get chronological context around a specific observation or time period. " +
            "Use this to understand what was happening around a specific event or date.",
        parameters: {
            type: "object",
            properties: {
                query: { type: "string", description: "Search query or observation ID to get context around" },
                limit: { type: "number", description: "Number of observations to return (default 10)" },
            },
            required: ["query"],
        },
        execute: async (_toolCallId, params) => {
            const query = String(params.query || "");
            const limit = Number(params.limit) || 10;
            const qs = new URLSearchParams({ query, limit: String(limit) });
            const result = await workerGetText(workerPort, `/api/timeline?${qs}`, api.logger);
            if (result) {
                return { content: [{ type: "text", text: result }] };
            }
            return { content: [{ type: "text", text: "Timeline unavailable — worker may still be initializing." }] };
        },
    });
    api.logger.info(`[claude-mem] OpenClaw plugin loaded — v1.0.0 (worker: 127.0.0.1:${workerPort})`);
}
