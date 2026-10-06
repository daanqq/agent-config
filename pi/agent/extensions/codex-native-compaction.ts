import { randomUUID } from "node:crypto";
import {
  convertToLlm,
  getLatestCompactionEntry,
  type ExtensionAPI,
  type SessionEntry,
} from "@earendil-works/pi-coding-agent";

const DETAILS_KIND = "openai-codex-native";
const MARKER = "[openai-codex-native-checkpoint";
const BETA_HEADER = "x-codex-beta-features";
const BETA_FEATURE = "remote_compaction_v2";

type Item = Record<string, unknown>;
type Details = { kind: typeof DETAILS_KIND; model: string; item: Item };

function isCodex(model: { provider?: string; api?: string } | undefined): boolean {
  return model?.provider === "openai-codex" && model.api === "openai-codex-responses";
}

function latestCheckpoint(branch: SessionEntry[]): Details | undefined {
  const details = getLatestCompactionEntry(branch)?.details as Partial<Details> | undefined;
  return details?.kind === DETAILS_KIND && typeof details.item?.encrypted_content === "string"
    ? (details as Details)
    : undefined;
}

function isMarker(item: Item): boolean {
  if (item.role !== "user" || !Array.isArray(item.content)) return false;
  return item.content.some((part: Item) => typeof part.text === "string" && part.text.includes(MARKER));
}

// Pi sends the compaction summary as a user message; Codex expects the opaque compaction item instead.
function withCheckpoint(input: unknown, checkpoint: Details | undefined): Item[] {
  const items = Array.isArray(input) ? (input as Item[]) : [];
  return checkpoint ? items.map((item) => (isMarker(item) ? checkpoint.item : item)) : items;
}

export default function (pi: ExtensionAPI) {
  pi.on("before_provider_headers", (event, ctx) => {
    if (isCodex(ctx.model)) event.headers[BETA_HEADER] = BETA_FEATURE;
  });

  pi.on("before_provider_request", (event, ctx) => {
    if (!isCodex(ctx.model)) return;
    const checkpoint = latestCheckpoint(ctx.sessionManager.getBranch());
    const payload = event.payload as Item;
    if (!checkpoint || !Array.isArray(payload.input)) return;
    return { ...payload, input: withCheckpoint(payload.input, checkpoint) };
  });

  pi.on("session_before_compact", async (event, ctx) => {
    const model = ctx.model;
    if (!model || !isCodex(model)) return;

    const { preparation, signal } = event;
    const previous = latestCheckpoint(event.branchEntries);
    const activeTools = new Set(pi.getActiveTools());
    const messages = [...preparation.messagesToSummarize, ...preparation.turnPrefixMessages];
    if (preparation.previousSummary) {
      messages.unshift({
        role: "compactionSummary",
        summary: preparation.previousSummary,
        tokensBefore: 0,
        timestamp: Date.now(),
      });
    }
    let item: Item | undefined;

    try {
      const response = await ctx.modelRegistry.complete(
        model,
        {
          systemPrompt: ctx.getSystemPrompt(),
          tools: pi.getAllTools().filter((tool) => activeTools.has(tool.name)),
          messages: convertToLlm(messages),
        },
        {
          signal,
          // A separate transport keeps the session's cached WebSocket continuation intact.
          transport: "sse",
          sessionId: ctx.sessionManager.getSessionId(),
          headers: { [BETA_HEADER]: BETA_FEATURE },
          onPayload: (payload: unknown) => {
            const body = payload as Item;
            return { ...body, input: [...withCheckpoint(body.input, previous), { type: "compaction_trigger" }] };
          },
          onProviderStreamEvent: (data: unknown) => {
            const event = data as { type?: string; item?: Item };
            if (event.type === "response.output_item.done" && event.item?.type === "compaction") item = event.item;
          },
        },
      );
      if (response.stopReason === "error" || response.stopReason === "aborted") {
        throw new Error(response.errorMessage ?? response.stopReason);
      }
      if (typeof item?.encrypted_content !== "string") throw new Error("response has no compaction item");

      const details: Details = { kind: DETAILS_KIND, model: model.id, item };
      return {
        compaction: {
          // Pi finds the saved entry by its summary text, so every marker must be unique.
          summary: `${MARKER} ${model.id} ${randomUUID()}]\nEarlier context is an encrypted OpenAI Codex checkpoint that only OpenAI Codex models can read.`,
          firstKeptEntryId: preparation.firstKeptEntryId,
          tokensBefore: preparation.tokensBefore,
          usage: response.usage,
          details,
        },
      };
    } catch (error) {
      if (!signal.aborted) {
        ctx.ui.notify(`OpenAI compaction failed: ${error instanceof Error ? error.message : String(error)}`, "error");
      }
      return { cancel: true };
    }
  });
}
