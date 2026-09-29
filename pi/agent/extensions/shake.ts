import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { ExtensionAPI, ExtensionCommandContext } from "@mariozechner/pi-coding-agent";

type TextBlock = { type: "text"; text: string };
type ImageBlock = { type: "image"; [key: string]: unknown };
type ContentBlock = TextBlock | ImageBlock | { type?: string; [key: string]: unknown };
type MessageEntry = { type: "message"; id: string; message: { role?: string; content?: unknown; [key: string]: unknown } };
type CustomMessageEntry = { type: "custom_message"; id: string; content: string | ContentBlock[] };
type SessionEntry = MessageEntry | CustomMessageEntry | { type: string; id?: string; [key: string]: unknown };

type ShakeResult = {
  mode: "elide" | "images";
  toolResultsDropped: number;
  blocksDropped: number;
  imagesDropped: number;
  tokensFreed: number;
  artifactPath?: string;
};

const MIN_BLOCK_CHARS = 4_000;
const SHAKEN_PREFIX = "[shaken";

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part): part is TextBlock => part?.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n");
}

function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

function stripImages(content: unknown): { content: unknown; removed: number } {
  if (!Array.isArray(content)) return { content, removed: 0 };
  let removed = 0;
  const kept = content.filter((part) => {
    const drop = part?.type === "image";
    if (drop) removed++;
    return !drop;
  });
  return { content: kept.length ? kept : [{ type: "text", text: "[image removed]" }], removed };
}

function shakeLargeBlocks(text: string, originals: string[]): { text: string; blocksDropped: number; tokensFreed: number } {
  let blocksDropped = 0;
  let tokensFreed = 0;
  const replace = (match: string) => {
    if (match.length < MIN_BLOCK_CHARS || match.startsWith(SHAKEN_PREFIX)) return match;
    originals.push(match);
    blocksDropped++;
    const tokens = estimateTokens(match);
    const marker = `[shaken ~${tokens} tokens: large block removed]`;
    tokensFreed += Math.max(0, tokens - estimateTokens(marker));
    return marker;
  };

  return {
    // ponytail: regex handles common giant code/XML dumps; add a parser only if this bites.
    text: text.replace(/```[\s\S]*?```|<([A-Za-z][\w:-]*)\b[^>]*>[\s\S]*?<\/\1>/g, replace),
    blocksDropped,
    tokensFreed,
  };
}

async function writeArtifact(ctx: ExtensionCommandContext, originals: string[]): Promise<string | undefined> {
  if (originals.length === 0) return undefined;
  const sessionFile = ctx.sessionManager.getSessionFile();
  const baseDir = sessionFile ? dirname(sessionFile) : join(process.env.HOME ?? ctx.cwd, ".pi", "shake-artifacts");
  const artifactPath = join(baseDir, `shake-${Date.now()}.md`);
  await mkdir(dirname(artifactPath), { recursive: true });
  await writeFile(
    artifactPath,
    originals.map((text, i) => `### region ${i + 1}\n\n${text}`).join("\n\n"),
    "utf8",
  );
  return artifactPath;
}

function rewriteSession(ctx: ExtensionCommandContext) {
  const manager = ctx.sessionManager as unknown as { _buildIndex?: () => void; _rewriteFile?: () => void };
  manager._buildIndex?.();
  manager._rewriteFile?.();
}

async function shake(ctx: ExtensionCommandContext, mode: "elide" | "images"): Promise<ShakeResult> {
  await ctx.waitForIdle();

  const branch = ctx.sessionManager.getBranch() as SessionEntry[];
  const originals: string[] = [];
  const result: ShakeResult = { mode, toolResultsDropped: 0, blocksDropped: 0, imagesDropped: 0, tokensFreed: 0 };

  for (const entry of branch) {
    if (entry.type === "message") {
      if (mode === "images") {
        const stripped = stripImages(entry.message.content);
        entry.message.content = stripped.content;
        result.imagesDropped += stripped.removed;
        continue;
      }

      if (entry.message.role === "toolResult") {
        const original = textOf(entry.message.content);
        if (original && !original.startsWith(SHAKEN_PREFIX)) {
          originals.push(original);
          const tokens = estimateTokens(original);
          const marker = `[shaken ~${tokens} tokens: tool result removed]`;
          entry.message.content = [{ type: "text", text: marker }];
          result.toolResultsDropped++;
          result.tokensFreed += Math.max(0, tokens - estimateTokens(marker));
        }
        continue;
      }

      if (Array.isArray(entry.message.content)) {
        for (const part of entry.message.content) {
          if (part?.type !== "text" || typeof part.text !== "string") continue;
          const shaken = shakeLargeBlocks(part.text, originals);
          part.text = shaken.text;
          result.blocksDropped += shaken.blocksDropped;
          result.tokensFreed += shaken.tokensFreed;
        }
      }
    }

    if (mode === "images" && entry.type === "custom_message") {
      const stripped = stripImages(entry.content);
      entry.content = stripped.content as string | ContentBlock[];
      result.imagesDropped += stripped.removed;
    }
  }

  if (originals.length > 0) result.artifactPath = await writeArtifact(ctx, originals);
  if (result.toolResultsDropped || result.blocksDropped || result.imagesDropped) rewriteSession(ctx);
  return result;
}

function formatResult(result: ShakeResult): string {
  if (result.mode === "images") {
    return result.imagesDropped ? `Dropped ${result.imagesDropped} image(s).` : "No images found in this session.";
  }
  const parts = [];
  if (result.toolResultsDropped) parts.push(`${result.toolResultsDropped} tool result(s)`);
  if (result.blocksDropped) parts.push(`${result.blocksDropped} block(s)`);
  if (!parts.length) return "Nothing to shake.";
  const artifact = result.artifactPath ? ` Originals saved: ${result.artifactPath}` : "";
  return `Shook ${parts.join(" + ")} (~${result.tokensFreed} tokens freed).${artifact}`;
}

function parseMode(args: string): "elide" | "images" | undefined {
  const mode = args.trim().toLowerCase() || "elide";
  return mode === "elide" || mode === "images" ? mode : undefined;
}

export default function (pi: ExtensionAPI) {
  pi.registerCommand("shake", {
    description: "Drop heavy content from context (tool results, large blocks, or images)",
    handler: async (args, ctx) => {
      const mode = parseMode(args);
      if (!mode) {
        ctx.ui.notify('Usage: /shake [elide|images]', "warning");
        return;
      }

      const result = await shake(ctx, mode);
      ctx.ui.notify(formatResult(result), result.toolResultsDropped || result.blocksDropped || result.imagesDropped ? "info" : "warning");
    },
  });
}
