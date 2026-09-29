import { appendFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type Message = {
  role?: string;
  content?: unknown;
  sections?: Record<string, string | null>;
  toolsAdded?: unknown[];
  command?: string;
  output?: string;
  summary?: string;
};

type Usage = {
  input?: number;
  output?: number;
  cacheRead?: number;
  cacheWrite?: number;
  totalTokens?: number;
  cost?: { input?: number; output?: number; cacheRead?: number; cacheWrite?: number; total?: number };
};

const LOG_PATH = process.env.PI_TOKEN_EFFICIENCY_LOG?.trim() || join(
  process.env.XDG_CACHE_HOME?.trim() || join(process.env.HOME || ".", ".cache"),
  "pi",
  "token-efficiency",
  "events.jsonl",
);

function tokens(chars: number): number {
  return Math.ceil(Math.max(0, chars) / 4);
}

function contentChars(content: unknown): number {
  if (typeof content === "string") return content.length;
  if (!Array.isArray(content)) return 0;
  return content.reduce((total, block) => {
    if (!block || typeof block !== "object") return total;
    const value = block as { type?: string; text?: string; thinking?: string; name?: string; arguments?: unknown };
    if (value.type === "text") return total + (value.text?.length ?? 0);
    if (value.type === "thinking") return total + (value.thinking?.length ?? 0);
    if (value.type === "toolCall") {
      return total + (value.name?.length ?? 0) + JSON.stringify(value.arguments ?? {}).length;
    }
    if (value.type === "image") return total + 4_800;
    return total;
  }, 0);
}

function messageChars(message: Message): number {
  switch (message.role) {
    case "assistant":
    case "user":
    case "toolResult":
    case "custom":
      return contentChars(message.content);
    case "bashExecution":
      return (message.command?.length ?? 0) + (message.output?.length ?? 0);
    case "branchSummary":
    case "compactionSummary":
      return message.summary?.length ?? 0;
    default:
      return 0;
  }
}

function promptSources(
  messages: readonly Message[],
  systemPrompt: string,
  tools: readonly unknown[],
  activeToolNames: readonly string[],
) {
  const source = {
    systemPrompt: 0,
    toolPrompt: 0,
    toolDefinitions: 0,
    contextFiles: 0,
    skills: 0,
    userMessages: 0,
    assistantHistory: 0,
    toolOutput: 0,
    summaries: 0,
    extensions: 0,
  };
  const sections = [...systemPrompt.matchAll(/<([a-z][a-z0-9_-]*)>([\s\S]*?)<\/\1>/g)];
  let sectionChars = 0;
  for (const match of sections) {
    const name = match[1];
    const size = tokens(match[2].length);
    sectionChars += match[0].length;
    if (name === "tools") source.toolPrompt += size;
    else if (name === "project_context") source.contextFiles += size;
    else if (name === "skills" || name === "available_skills") source.skills += size;
    else source.systemPrompt += size;
  }
  source.systemPrompt += tokens(Math.max(0, systemPrompt.length - sectionChars));
  const active = new Set(activeToolNames);
  let toolDefinitionChars = 0;
  for (const tool of tools) {
    if (typeof tool !== "object" || tool === null) continue;
    const value = tool as { name?: string; description?: string; parameters?: unknown };
    if (!active.has(value.name ?? "")) continue;
    toolDefinitionChars += JSON.stringify({
      name: value.name,
      description: value.description,
      parameters: value.parameters,
    }).length;
  }
  source.toolDefinitions = tokens(toolDefinitionChars);

  for (const message of messages) {
    if (message.role === "system") continue;
    const size = tokens(messageChars(message));
    if (message.role === "user") source.userMessages += size;
    else if (message.role === "assistant") source.assistantHistory += size;
    else if (message.role === "toolResult" || message.role === "bashExecution") source.toolOutput += size;
    else if (message.role === "branchSummary" || message.role === "compactionSummary") source.summaries += size;
    else source.extensions += size;
  }
  return source;
}

function hash(text: string): string {
  return createHash("sha256").update(text).digest("hex").slice(0, 16);
}

function usageTotal(usage: Usage | undefined): number {
  if (!usage) return 0;
  return (usage.input ?? 0) + (usage.output ?? 0) + (usage.cacheRead ?? 0) + (usage.cacheWrite ?? 0);
}

export default function tokenEfficiencyExtension(pi: ExtensionAPI) {
  let sessionId = "unknown";
  let taskNumber = 0;
  let taskId = "unknown:0";
  let requestNumber = 0;
  let pending: Array<{ requestNumber: number; taskId: string; sourceTokens: ReturnType<typeof promptSources>; toolCount: number; toolHash: string }> = [];
  let writeChain = Promise.resolve();

  const record = (event: Record<string, unknown>) => {
    const line = `${JSON.stringify({ schema: 1, at: new Date().toISOString(), sessionId, ...event })}\n`;
    writeChain = writeChain.then(async () => {
      await mkdir(dirname(LOG_PATH), { recursive: true, mode: 0o700 });
      await appendFile(LOG_PATH, line, { encoding: "utf8", mode: 0o600 });
    }).catch(() => undefined);
  };

  pi.on("session_start", (_event, ctx) => {
    sessionId = ctx.sessionManager.getSessionId();
    taskNumber = 0;
    taskId = `${sessionId}:0`;
    requestNumber = 0;
    pending = [];
  });

  pi.on("before_agent_start", (event, ctx) => {
    taskNumber += 1;
    taskId = `${sessionId}:${taskNumber}`;
    record({
      kind: "task",
      taskId,
      promptChars: event.prompt.length,
      promptHash: hash(event.prompt),
      model: ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : undefined,
    });
  });

  pi.on("context", (event, ctx) => {
    const names = pi.getActiveTools();
    const toolHash = hash(names.join("\n"));
    pending.push({
      requestNumber: ++requestNumber,
      taskId,
      sourceTokens: promptSources(event.messages as Message[], ctx.getSystemPrompt(), pi.getAllTools(), names),
      toolCount: names.length,
      toolHash,
    });
  });

  pi.on("message_end", (event) => {
    if (event.message.role !== "assistant") return;
    const request = pending.shift();
    const usage = event.message.usage as Usage | undefined;
    record({
      kind: "request",
      taskId: request?.taskId ?? taskId,
      requestNumber: request?.requestNumber ?? requestNumber,
      model: `${event.message.provider}/${event.message.model}`,
      stopReason: event.message.stopReason,
      hasToolCalls: event.message.content.some((block) => block.type === "toolCall"),
      usage,
      usageTotal: usageTotal(usage),
      sourceTokens: request?.sourceTokens ?? {},
      toolCount: request?.toolCount ?? pi.getActiveTools().length,
      toolHash: request?.toolHash ?? hash(pi.getActiveTools().join("\n")),
    });
  });

  pi.on("tool_execution_end", (event) => {
    record({
      kind: "tool",
      taskId,
      tool: event.toolName,
      isError: event.isError,
    });
  });

  pi.on("tool_result", (event) => {
    if (!event.usage) return;
    record({
      kind: "nested-request",
      taskId,
      tool: event.toolName,
      usage: event.usage,
      usageTotal: usageTotal(event.usage),
    });
  });

  pi.on("session_shutdown", async () => {
    await writeChain;
  });
}
