interface PluginLogger {
    debug?: (message: string) => void;
    info: (message: string) => void;
    warn: (message: string) => void;
    error: (message: string) => void;
}
interface PluginServiceContext {
    config: Record<string, unknown>;
    workspaceDir?: string;
    stateDir: string;
    logger: PluginLogger;
}
interface PluginCommandContext {
    senderId?: string;
    channel: string;
    isAuthorizedSender: boolean;
    args?: string;
    commandBody: string;
    config: Record<string, unknown>;
}
type PluginCommandResult = string | {
    text: string;
} | {
    text: string;
    format?: string;
};
interface BeforeAgentStartEvent {
    prompt?: string;
}
interface ToolResultPersistEvent {
    toolName?: string;
    params?: Record<string, unknown>;
    message?: {
        content?: Array<{
            type: string;
            text?: string;
        }>;
    };
}
interface AgentEndEvent {
    messages?: Array<{
        role: string;
        content: string | Array<{
            type: string;
            text?: string;
        }>;
    }>;
}
interface SessionStartEvent {
    sessionId: string;
    resumedFrom?: string;
}
interface AfterCompactionEvent {
    messageCount: number;
    tokenCount?: number;
    compactedCount: number;
}
interface SessionEndEvent {
    sessionId: string;
    messageCount: number;
    durationMs?: number;
}
interface MessageReceivedEvent {
    from: string;
    content: string;
    timestamp?: number;
    metadata?: Record<string, unknown>;
}
interface EventContext {
    sessionKey?: string;
    workspaceDir?: string;
    agentId?: string;
}
interface MessageContext {
    channelId: string;
    accountId?: string;
    conversationId?: string;
}
type EventCallback<T> = (event: T, ctx: EventContext) => void | Promise<void>;
type MessageEventCallback<T> = (event: T, ctx: MessageContext) => void | Promise<void>;
interface AgentToolResult {
    content: Array<{
        type: string;
        text?: string;
    }>;
}
interface AgentTool {
    name: string;
    label?: string;
    description: string;
    parameters: Record<string, unknown>;
    execute: (toolCallId: string, params: Record<string, unknown>) => Promise<AgentToolResult>;
}
interface OpenClawPluginApi {
    id: string;
    name: string;
    version?: string;
    source: string;
    config: Record<string, unknown>;
    pluginConfig?: Record<string, unknown>;
    logger: PluginLogger;
    registerTool: (tool: AgentTool, opts?: {
        optional?: boolean;
    }) => void;
    registerService: (service: {
        id: string;
        start: (ctx: PluginServiceContext) => void | Promise<void>;
        stop?: (ctx: PluginServiceContext) => void | Promise<void>;
    }) => void;
    registerCommand: (command: {
        name: string;
        description: string;
        acceptsArgs?: boolean;
        requireAuth?: boolean;
        handler: (ctx: PluginCommandContext) => PluginCommandResult | Promise<PluginCommandResult>;
    }) => void;
    on: ((event: "before_agent_start", callback: EventCallback<BeforeAgentStartEvent>) => void) & ((event: "tool_result_persist", callback: EventCallback<ToolResultPersistEvent>) => void) & ((event: "agent_end", callback: EventCallback<AgentEndEvent>) => void) & ((event: "session_start", callback: EventCallback<SessionStartEvent>) => void) & ((event: "session_end", callback: EventCallback<SessionEndEvent>) => void) & ((event: "message_received", callback: MessageEventCallback<MessageReceivedEvent>) => void) & ((event: "after_compaction", callback: EventCallback<AfterCompactionEvent>) => void) & ((event: "gateway_start", callback: EventCallback<Record<string, never>>) => void);
    runtime: {
        channel: Record<string, Record<string, (...args: unknown[]) => Promise<unknown>>>;
    };
}
export default function claudeMemPlugin(api: OpenClawPluginApi): void;
export {};
