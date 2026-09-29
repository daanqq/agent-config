import { mkdtemp, writeFile } from "node:fs/promises";
import { lookup } from "node:dns/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { getMarkdownTheme, keyHint } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Markdown, Text, truncateToWidth, type Component } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const CODEX_MODEL = "gpt-5.6-luna";
const CODEX_BASE_URL = "http://127.0.0.1:8317/backend-api";
const FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v2/scrape";
const MAX_OUTPUT_BYTES = 50 * 1024;
const MAX_OUTPUT_LINES = 2_000;
const COLLAPSED_RENDER_LINES = 10;

type SearchInput = { query: string; purpose?: string };
type FetchInput = { url: string };
type JsonObject = Record<string, unknown>;

function asObject(value: unknown): JsonObject | undefined {
	return value && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : undefined;
}

function truncateOutput(text: string): { text: string; truncated: boolean } {
	const lines = text.split("\n");
	let bytes = 0;
	let count = 0;

	for (; count < lines.length && count < MAX_OUTPUT_LINES; count++) {
		const lineBytes = Buffer.byteLength(lines[count], "utf8") + (count > 0 ? 1 : 0);
		if (bytes + lineBytes > MAX_OUTPUT_BYTES) break;
		bytes += lineBytes;
	}

	if (count === lines.length) return { text, truncated: false };
	return { text: lines.slice(0, count).join("\n"), truncated: true };
}

function textContent(result: { content: Array<{ type: string; text?: string }> }): string {
	const content = result.content.find((item) => item.type === "text");
	return content?.text ?? "";
}

function sourceCount(text: string): number {
	return new Set(text.match(/https:\/\/[^\s)]+/g) ?? []).size;
}

function renderCollapsibleMarkdown(text: string, expanded: boolean, muted: (text: string) => string): Component {
	const markdown = new Markdown(text, 0, 0, getMarkdownTheme());
	return {
		render(width) {
			const lines = markdown.render(width);
			if (expanded || lines.length <= COLLAPSED_RENDER_LINES) return lines;

			const hiddenLines = lines.length - COLLAPSED_RENDER_LINES + 1;
			const hint = muted(`... (${hiddenLines} more lines; ${keyHint("app.tools.expand", "to expand")})`);
			return [...lines.slice(0, COLLAPSED_RENDER_LINES - 1), truncateToWidth(hint, width)];
		},
		invalidate() {
			markdown.invalidate();
		},
	};
}

async function saveFullOutput(text: string): Promise<string> {
	const directory = await mkdtemp(join(tmpdir(), "pi-web-access-"));
	const path = join(directory, "content.md");
	await writeFile(path, text, { encoding: "utf8", mode: 0o600 });
	return path;
}

function publicAddress(address: string): boolean {
	const normalized = address.toLowerCase();
	if (normalized === "::1" || normalized === "0.0.0.0" || normalized === "::") return false;
	if (normalized.startsWith("127.") || normalized.startsWith("10.") || normalized.startsWith("192.168.")) return false;
	if (normalized.startsWith("169.254.") || /^172\.(1[6-9]|2\d|3[01])\./.test(normalized)) return false;
	if (normalized.startsWith("::ffff:127.") || normalized.startsWith("::ffff:10.") || normalized.startsWith("::ffff:192.168.")) return false;
	if (normalized.startsWith("fc") || normalized.startsWith("fd") || normalized.startsWith("fe8") || normalized.startsWith("fe9") || normalized.startsWith("fea") || normalized.startsWith("feb")) return false;
	return true;
}

async function validatePublicUrl(value: string): Promise<string> {
	let url: URL;
	try {
		url = new URL(value);
	} catch {
		throw new Error("A valid URL is required.");
	}
	if (url.protocol !== "https:") throw new Error("Only public HTTPS URLs are supported.");
	if (url.username || url.password) throw new Error("URLs containing credentials are not supported.");
	if (!url.hostname || url.hostname === "localhost") throw new Error("Private and local URLs are not supported.");

	const addresses = await lookup(url.hostname, { all: true, verbatim: true });
	if (addresses.length === 0 || addresses.some(({ address }) => !publicAddress(address))) {
		throw new Error("The URL resolves to a private or local address.");
	}
	return url.href;
}

function parseSseData(chunk: string): string | undefined {
	const data = chunk
		.split(/\r?\n/)
		.filter((line) => line.startsWith("data:"))
		.map((line) => line.slice(5).trim())
		.join("\n")
		.trim();
	return data && data !== "[DONE]" ? data : undefined;
}

async function codexSearch(input: SearchInput, signal: AbortSignal): Promise<string> {
	const apiKey = process.env.CLIPROXY_API_KEY?.trim();
	if (!apiKey) throw new Error("CLIPROXY_API_KEY is not set.");

	const purpose = input.purpose?.trim() || "general research support";
	const prompt = `Search the internet for: ${input.query}\n\nPurpose: ${purpose}\n\nReturn a concise research summary with:\n- 3 to 7 key findings\n- for every finding: title, why it matters for this purpose, and a full canonical URL (https://...)\n- if multiple sources disagree, call that out\n- finish with a short recommendation on which source(s) to trust first.`;
	const response = await fetch(`${(process.env.CLIPROXY_BASE_URL || CODEX_BASE_URL).replace(/\/$/, "")}/codex/responses`, {
		method: "POST",
		headers: { "X-Api-Key": apiKey, "content-type": "application/json", accept: "text/event-stream" },
		body: JSON.stringify({
			model: CODEX_MODEL,
			store: false,
			stream: true,
			instructions: "You are a fast web research assistant. Always produce practical summaries and include full source URLs (no shortened links).",
			input: [{ role: "user", content: prompt }],
			tools: [{ type: "web_search" }],
			tool_choice: "auto",
		}),
		signal: AbortSignal.any([signal, AbortSignal.timeout(120_000)]),
	});
	if (!response.ok || !response.body) throw new Error(`Codex request failed (${response.status}): ${await response.text()}`);

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";
	let text = "";
	let fallback = "";
	while (true) {
		const { done, value } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });
		let index;
		while ((index = buffer.indexOf("\n\n")) !== -1) {
			const data = parseSseData(buffer.slice(0, index));
			buffer = buffer.slice(index + 2);
			if (!data) continue;
			let event: JsonObject | undefined;
			try { event = asObject(JSON.parse(data)); } catch { continue; }
			if (event?.type === "response.output_text.delta" && typeof event.delta === "string") text += event.delta;
			const item = asObject(event?.item);
			if (event?.type === "response.output_item.done" && item?.type === "message") {
				const parts = Array.isArray(item.content) ? item.content : [];
				fallback = parts
					.map(asObject)
					.filter((part): part is JsonObject => part?.type === "output_text" && typeof part.text === "string")
					.map((part) => part.text as string)
					.join("\n");
			}
			if (event?.type === "error" || event?.type === "response.failed") {
				const responseError = asObject(asObject(event.response)?.error);
				const message = typeof event.message === "string" ? event.message : responseError?.message;
				throw new Error(typeof message === "string" ? message : "Codex stream failed");
			}
		}
	}
	const result = (text || fallback).trim();
	if (!result) throw new Error("Codex returned an empty response.");
	return result;
}

async function firecrawlFetch(input: FetchInput, signal: AbortSignal): Promise<{ text: string; fullLength: number; fullPath?: string }> {
	const url = await validatePublicUrl(input.url);
	const apiKey = process.env.FIRECRAWL_API_KEY?.trim();
	if (!apiKey) throw new Error("FIRECRAWL_API_KEY is not set.");

	const response = await fetch(FIRECRAWL_ENDPOINT, {
		method: "POST",
		headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
		body: JSON.stringify({ url, formats: ["markdown"] }),
		signal: AbortSignal.any([signal, AbortSignal.timeout(60_000)]),
	});
	let payload: JsonObject | undefined;
	try { payload = await response.json(); } catch { throw new Error(`Firecrawl returned a non-JSON response (HTTP ${response.status}).`); }
	const data = asObject(payload?.data);
	if (!response.ok || payload?.success !== true) {
		const detail = typeof payload?.error === "string" ? payload.error : `HTTP ${response.status}`;
		throw new Error(`Firecrawl scrape failed: ${detail}`);
	}
	const markdown = data?.markdown;
	if (typeof markdown !== "string" || !markdown.trim()) throw new Error("Firecrawl returned no Markdown content.");

	const bounded = truncateOutput(markdown);
	return {
		text: bounded.truncated
			? `${bounded.text}\n\n[Output truncated at ${MAX_OUTPUT_LINES} lines or ${MAX_OUTPUT_BYTES} bytes.]`
			: bounded.text,
		fullLength: markdown.length,
		...(bounded.truncated ? { fullPath: await saveFullOutput(markdown) } : {}),
	};
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "web_search",
		label: "Web Search",
		description: "Search the internet through Codex web search and return a concise source-linked research summary.",
		promptSnippet: "Search the internet for current information and source URLs",
		parameters: Type.Object({
			query: Type.String({ description: "The research question or search topic" }),
			purpose: Type.Optional(Type.String({ description: "How the research will be used" })),
		}),
		async execute(_toolCallId, params, signal) {
			const fullResult = await codexSearch(params, signal);
			const result = truncateOutput(fullResult);
			const fullPath = result.truncated ? await saveFullOutput(fullResult) : undefined;
			const sources = sourceCount(fullResult);
			return {
				content: [{ type: "text", text: result.text + (result.truncated ? `\n\n[Output truncated. Full content saved to: ${fullPath}]` : "") }],
				details: { model: CODEX_MODEL, sources, truncated: result.truncated, ...(fullPath ? { fullPath } : {}) },
			};
		},
		renderCall(args, theme, context) {
			const state = context.state as { sources?: number };
			const suffix = typeof state.sources === "number" ? ` ${state.sources} sources` : "";
			return new Text(
				theme.fg("toolTitle", theme.bold("web_search")) +
				` ${theme.fg("muted", `"${args.query}"`)}${theme.fg("dim", suffix)}`,
				0,
				0,
			);
		},
		renderResult(result, { expanded, isPartial }, theme, context) {
			if (isPartial) return new Text(theme.fg("warning", "Searching..."), 0, 0);
			const details = context.state as { sources?: number };
			const sources = typeof result.details?.sources === "number" ? result.details.sources : sourceCount(textContent(result));
			if (details.sources !== sources) {
				details.sources = sources;
			}
			return renderCollapsibleMarkdown(textContent(result), expanded, (text) => theme.fg("muted", text));
		},
	});

	pi.registerTool({
		name: "firecrawl_fetch",
		label: "Firecrawl Fetch",
		description: "Fetch one public HTTPS URL through Firecrawl and return its readable Markdown content.",
		promptSnippet: "Fetch a specific public web page as Markdown through Firecrawl",
		parameters: Type.Object({ url: Type.String({ description: "Public HTTPS URL to fetch" }) }),
		async execute(_toolCallId, params, signal) {
			const result = await firecrawlFetch(params, signal);
			return {
				content: [{ type: "text", text: result.text + (result.fullPath ? `\n\nFull content saved to: ${result.fullPath}` : "") }],
				details: { url: params.url, fullLength: result.fullLength, ...(result.fullPath ? { fullPath: result.fullPath } : {}) },
			};
		},
		renderCall(args, theme) {
			return new Text(
				theme.fg("toolTitle", theme.bold("firecrawl_fetch")) + ` ${theme.fg("muted", args.url)}`,
				0,
				0,
			);
		},
		renderResult(result, { expanded, isPartial }, theme) {
			if (isPartial) return new Text(theme.fg("warning", "Fetching..."), 0, 0);
			return renderCollapsibleMarkdown(textContent(result), expanded, (text) => theme.fg("muted", text));
		},
	});
}
