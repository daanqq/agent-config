/**
 * Agent Pulse Extension
 *
 * Unified pi agent activity signals:
 * - replaces the built-in working indicator with a themed thinking shimmer;
 * - owns the terminal title while loaded;
 * - shows working/tool/done states;
 * - rings the terminal bell when an agent turn finishes.
 *
 * Do not enable together with other extensions that continuously call ctx.ui.setTitle()
 * or replace the built-in working indicator.
 */

import path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { truncateToWidth } from "@earendil-works/pi-tui";
import {
	calculateTextStreamMetrics,
	type TextStreamMetrics,
} from "./shared/text-stream-metrics.ts";

const SPINNER_VERBS = [
	"Accomplishing",
	"Actioning",
	"Actualizing",
	"Architecting",
	"Baking",
	"Beaming",
	"Beboppin'",
	"Befuddling",
	"Billowing",
	"Blanching",
	"Bloviating",
	"Boogieing",
	"Boondoggling",
	"Booping",
	"Bootstrapping",
	"Brewing",
	"Bunning",
	"Burrowing",
	"Calculating",
	"Canoodling",
	"Caramelizing",
	"Cascading",
	"Catapulting",
	"Cerebrating",
	"Channeling",
	"Channelling",
	"Choreographing",
	"Churning",
	"Clauding",
	"Coalescing",
	"Cogitating",
	"Combobulating",
	"Composing",
	"Computing",
	"Concocting",
	"Considering",
	"Contemplating",
	"Cooking",
	"Crafting",
	"Creating",
	"Crunching",
	"Crystallizing",
	"Cultivating",
	"Deciphering",
	"Deliberating",
	"Determining",
	"Dilly-dallying",
	"Discombobulating",
	"Doing",
	"Doodling",
	"Drizzling",
	"Ebbing",
	"Effecting",
	"Elucidating",
	"Embellishing",
	"Enchanting",
	"Envisioning",
	"Evaporating",
	"Fermenting",
	"Fiddle-faddling",
	"Finagling",
	"Flambéing",
	"Flibbertigibbeting",
	"Flowing",
	"Flummoxing",
	"Fluttering",
	"Forging",
	"Forming",
	"Frolicking",
	"Frosting",
	"Gallivanting",
	"Galloping",
	"Garnishing",
	"Generating",
	"Gesticulating",
	"Germinating",
	"Gitifying",
	"Grooving",
	"Gusting",
	"Harmonizing",
	"Hashing",
	"Hatching",
	"Herding",
	"Honking",
	"Hullaballooing",
	"Hyperspacing",
	"Ideating",
	"Imagining",
	"Improvising",
	"Incubating",
	"Inferring",
	"Infusing",
	"Ionizing",
	"Jitterbugging",
	"Julienning",
	"Kneading",
	"Leavening",
	"Levitating",
	"Lollygagging",
	"Manifesting",
	"Marinating",
	"Meandering",
	"Metamorphosing",
	"Misting",
	"Moonwalking",
	"Moseying",
	"Mulling",
	"Mustering",
	"Musing",
	"Nebulizing",
	"Nesting",
	"Newspapering",
	"Noodling",
	"Nucleating",
	"Orbiting",
	"Orchestrating",
	"Osmosing",
	"Perambulating",
	"Percolating",
	"Perusing",
	"Philosophising",
	"Photosynthesizing",
	"Pollinating",
	"Pondering",
	"Pontificating",
	"Pouncing",
	"Precipitating",
	"Prestidigitating",
	"Processing",
	"Proofing",
	"Propagating",
	"Puttering",
	"Puzzling",
	"Quantumizing",
	"Razzle-dazzling",
	"Razzmatazzing",
	"Recombobulating",
	"Reticulating",
	"Roosting",
	"Ruminating",
	"Sautéing",
	"Scampering",
	"Schlepping",
	"Scurrying",
	"Seasoning",
	"Shenaniganing",
	"Shimmying",
	"Simmering",
	"Skedaddling",
	"Sketching",
	"Slithering",
	"Smooshing",
	"Sock-hopping",
	"Spelunking",
	"Spinning",
	"Sprouting",
	"Stewing",
	"Sublimating",
	"Swirling",
	"Swooping",
	"Symbioting",
	"Synthesizing",
	"Tempering",
	"Thinking",
	"Thundering",
	"Tinkering",
	"Tomfoolering",
	"Topsy-turvying",
	"Transfiguring",
	"Transmuting",
	"Twisting",
	"Undulating",
	"Unfurling",
	"Unravelling",
	"Vibing",
	"Waddling",
	"Wandering",
	"Warping",
	"Whatchamacalliting",
	"Whirlpooling",
	"Whirring",
	"Whisking",
	"Wibbling",
	"Working",
	"Wrangling",
	"Zesting",
	"Zigzagging",
] as const;

const SPINNER_CHARACTERS = ["·", "✢", "✶", "✻", "✽"] as const;
const SPINNER_FRAMES = [...SPINNER_CHARACTERS, ...[...SPINNER_CHARACTERS].reverse()];
const SPINNER_RENDER_INTERVAL_MS = 120;
const SPINNER_FRAME_MS = 120;
const SHIMMER_FRAME_MS = 50;
const SHIMMER_TRAILING_GAP = 4;
const TITLE_DONE_HOLD_MS = 8000;
const MAX_SESSION_LENGTH = 36;
const MAX_CWD_LENGTH = 24;
const PULSE_WIDGET_KEY = "agent-pulse";

type ColorFn = (text: string) => string;

function sampleVerb(): string {
	return SPINNER_VERBS[Math.floor(Math.random() * SPINNER_VERBS.length)] ?? "Thinking";
}

function spinnerFrame(elapsedMs: number): string {
	return SPINNER_FRAMES[Math.floor(elapsedMs / SPINNER_FRAME_MS) % SPINNER_FRAMES.length] ?? "✻";
}

function formatElapsed(ms: number): string {
	const totalSeconds = Math.floor(ms / 1000);
	if (totalSeconds < 60) return `${totalSeconds}s`;
	const minutes = Math.floor(totalSeconds / 60);
	const seconds = totalSeconds % 60;
	return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
}

function formatTtft(ms: number): string {
	return `${(ms / 1000).toFixed(1)}ttft`;
}

function formatFinalDuration(ms: number, metrics?: TextStreamMetrics): string {
	const parts = [`Worked for ${formatElapsed(ms)}`];
	if (metrics?.ttftMs !== undefined) parts.push(formatTtft(metrics.ttftMs));
	if (metrics?.tps !== undefined) parts.push(`${metrics.tps}tps`);
	return parts.join(" / ");
}

function renderShimmeredMessage(message: string, elapsedMs: number, base: ColorFn, bright: ColorFn): string {
	const chars = Array.from(message);
	const shimmerCenter = Math.floor(elapsedMs / SHIMMER_FRAME_MS) % (chars.length + SHIMMER_TRAILING_GAP);
	return chars
		.map((char, index) => {
			const distance = Math.abs(index - shimmerCenter);
			return distance <= 1 ? bright(char) : base(char);
		})
		.join("");
}

function truncate(value: string, maxLength: number): string {
	if (value.length <= maxLength) return value;
	if (maxLength <= 1) return value.slice(0, maxLength);
	return `${value.slice(0, maxLength - 1)}…`;
}

function cwdLabel(ctx?: ExtensionContext): string {
	const cwd = ctx?.cwd ?? process.cwd();
	return truncate(path.basename(cwd) || cwd, MAX_CWD_LENGTH);
}

function contextLabel(pi: ExtensionAPI, ctx?: ExtensionContext): string {
	const session = pi.getSessionName();
	const cwd = cwdLabel(ctx);
	if (!session) return cwd;
	return `${truncate(session, MAX_SESSION_LENGTH)} - ${cwd}`;
}

function ringBell() {
	process.stdout.write("\x07");
}

declare global {
	var __piAgentPulseEditorLine: ((width: number, borderColor: ColorFn) => string | undefined) | undefined;
	var __piAgentPulseEditorAvailable: boolean | undefined;
	var __piAgentPulseRequestRender: (() => void) | undefined;
}

export default function (pi: ExtensionAPI) {
	let renderTimer: ReturnType<typeof setInterval> | null = null;
	let titleDoneTimer: ReturnType<typeof setTimeout> | null = null;
	let verb = "Thinking";
	let activity = "waiting for provider";
	let startTime = 0;
	let totalPausedMs = 0;
	let pauseStartTime: number | null = null;
	let active = false;
	let lastFrame = "✻";
	let lastToolName: string | undefined;
	let providerRequestStartedAt: number | undefined;
	let firstTextDeltaAt: number | undefined;
	let lastTextDeltaAt: number | undefined;
	let latestTextStreamMetrics: TextStreamMetrics | undefined;
	let frozenPulseColor: ColorFn | null = null;
	let contextLabelCache = "";
	let pulseMode: "hidden" | "active" | "final" = "hidden";
	let finalPulseText = "";
	const activeTools = new Map<string, string>();
	const pausedToolIds = new Set<string>();
	let editorPulseAvailable = false;

	function refreshContextLabel(ctx?: ExtensionContext) {
		contextLabelCache = contextLabel(pi, ctx);
	}

	function currentContextLabel(ctx?: ExtensionContext): string {
		if (!contextLabelCache) refreshContextLabel(ctx);
		return contextLabelCache;
	}

	function getElapsedMs(): number {
		if (pauseStartTime !== null) return pauseStartTime - startTime - totalPausedMs;
		return Date.now() - startTime - totalPausedMs;
	}

	function clearRenderTimer() {
		if (renderTimer) {
			clearInterval(renderTimer);
			renderTimer = null;
		}
	}

	function clearTitleDoneTimer() {
		if (titleDoneTimer) {
			clearTimeout(titleDoneTimer);
			titleDoneTimer = null;
		}
	}

	function installEditorPulseRenderer() {
		globalThis.__piAgentPulseEditorLine = (width, borderColor) => {
			if (pulseMode === "hidden") return undefined;
			const base = frozenPulseColor ?? borderColor;
			frozenPulseColor = base;
			if (pulseMode === "final") {
				return truncateToWidth(`  ${base("✻")} ${base(finalPulseText)}`, width, "");
			}

			const elapsedMs = getElapsedMs();
			lastFrame = spinnerFrame(elapsedMs);
			const bright = (text: string) => `\x1b[1m${base(text)}\x1b[22m`;
			const line = `${verb}: ${activity}… ${formatElapsed(elapsedMs)}`;
			const rendered = `${base(lastFrame)} ${renderShimmeredMessage(line, elapsedMs, base, bright)}`;
			return truncateToWidth(`  ${rendered}`, width, "");
		};
	}

	function requestPulseRender() {
		globalThis.__piAgentPulseRequestRender?.();
	}

	function renderFallbackPulse(ctx: ExtensionContext, elapsedMs: number): string {
		const base = ctx.ui.theme.getThinkingBorderColor(pi.getThinkingLevel());
		const bright = (text: string) => `\x1b[1m${base(text)}\x1b[22m`;
		const line = `${verb}: ${activity}… ${formatElapsed(elapsedMs)}`;
		return ` ${base(lastFrame)} ${renderShimmeredMessage(line, elapsedMs, base, bright)}`;
	}

	function renderWidget(ctx: ExtensionContext) {
		const elapsedMs = getElapsedMs();
		lastFrame = spinnerFrame(elapsedMs);
		if (!editorPulseAvailable) {
			ctx.ui.setWidget(PULSE_WIDGET_KEY, [renderFallbackPulse(ctx, elapsedMs)]);
		}
		requestPulseRender();
	}

	function renderFinalWidget(finalElapsedMs: number, ctx: ExtensionContext) {
		finalPulseText = formatFinalDuration(finalElapsedMs, latestTextStreamMetrics);
		pulseMode = "final";
		if (!editorPulseAvailable) {
			const base = ctx.ui.theme.getThinkingBorderColor(pi.getThinkingLevel());
			ctx.ui.setWidget(PULSE_WIDGET_KEY, [` ${base("✻")} ${base(finalPulseText)}`]);
		}
		requestPulseRender();
	}

	function setIdleTitle(ctx: ExtensionContext) {
		ctx.ui.setTitle(currentContextLabel(ctx));
	}

	function setDoneTitle(ctx: ExtensionContext) {
		ctx.ui.setTitle(`${lastFrame} done - ${currentContextLabel(ctx)}`);
	}

	function renderTitle(ctx: ExtensionContext) {
		if (activeTools.size > 0 && lastToolName) {
			const extraTools = activeTools.size - 1;
			const suffix = extraTools > 0 ? ` +${extraTools}` : "";
			ctx.ui.setTitle(`⚙ ${lastToolName}${suffix} - ${currentContextLabel(ctx)}`);
			return;
		}

		const elapsedMs = getElapsedMs();
		lastFrame = spinnerFrame(elapsedMs);
		ctx.ui.setTitle(`${lastFrame} ${verb}: ${activity}… - ${currentContextLabel(ctx)}`);
	}

	function renderActive(ctx: ExtensionContext) {
		renderWidget(ctx);
		renderTitle(ctx);
	}

	function stopActiveTimerOnly() {
		clearRenderTimer();
		active = false;
	}

	function resetRuntimeState() {
		active = false;
		pauseStartTime = null;
		totalPausedMs = 0;
		activeTools.clear();
		pausedToolIds.clear();
		lastToolName = undefined;
		frozenPulseColor = null;
		pulseMode = "hidden";
		finalPulseText = "";
		editorPulseAvailable = false;
	}

	function resetToIdle(ctx: ExtensionContext) {
		clearRenderTimer();
		clearTitleDoneTimer();
		resetRuntimeState();
		globalThis.__piAgentPulseEditorLine = undefined;
		requestPulseRender();
		ctx.ui.setWidget(PULSE_WIDGET_KEY, undefined);
		ctx.ui.setWorkingVisible(true);
		refreshContextLabel(ctx);
		setIdleTitle(ctx);
	}

	function pauseElapsed() {
		if (!renderTimer || pauseStartTime !== null) return;
		pauseStartTime = Date.now();
	}

	function resumeElapsed() {
		if (pauseStartTime === null) return;
		totalPausedMs += Date.now() - pauseStartTime;
		pauseStartTime = null;
	}

	function start(ctx: ExtensionContext) {
		clearRenderTimer();
		clearTitleDoneTimer();
		resetRuntimeState();
		providerRequestStartedAt = undefined;
		firstTextDeltaAt = undefined;
		lastTextDeltaAt = undefined;
		latestTextStreamMetrics = undefined;
		verb = sampleVerb();
		activity = "waiting for provider";
		startTime = Date.now();
		totalPausedMs = 0;
		pauseStartTime = null;
		active = true;
		lastFrame = spinnerFrame(0);
		frozenPulseColor = null;
		pulseMode = "active";
		editorPulseAvailable = globalThis.__piAgentPulseEditorAvailable === true;
		if (editorPulseAvailable) {
			installEditorPulseRenderer();
			ctx.ui.setWorkingVisible(false);
		} else {
			ctx.ui.setWorkingVisible(false);
		}
		renderActive(ctx);
		// The custom editor pulse is animated here; the built-in fallback owns its animation.
		renderTimer = setInterval(() => renderWidget(ctx), SPINNER_RENDER_INTERVAL_MS);
	}

	function finish(ctx: ExtensionContext) {
		if (!active) {
			resetToIdle(ctx);
			return;
		}

		const finalElapsedMs = getElapsedMs();
		stopActiveTimerOnly();
		pauseStartTime = null;
		totalPausedMs = 0;
		activeTools.clear();
		lastToolName = undefined;
		renderFinalWidget(finalElapsedMs, ctx);
		ctx.ui.setWorkingVisible(true);
		setDoneTitle(ctx);
		ringBell();

		clearTitleDoneTimer();
		titleDoneTimer = setTimeout(() => {
			setIdleTitle(ctx);
			titleDoneTimer = null;
		}, TITLE_DONE_HOLD_MS);
	}

	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		resetToIdle(ctx);
	});

	pi.on("session_info_changed", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		refreshContextLabel(ctx);
		if (active) renderTitle(ctx);
		else setIdleTitle(ctx);
	});

	pi.on("agent_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		start(ctx);
	});

	pi.on("before_provider_request", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		providerRequestStartedAt = performance.now();
	});

	pi.on("message_start", (event, ctx) => {
		if (ctx.mode !== "tui") return;
		if (event.message.role !== "assistant") return;
		firstTextDeltaAt = undefined;
		lastTextDeltaAt = undefined;
	});

	pi.on("tool_execution_start", (event, ctx) => {
		if (ctx.mode !== "tui") return;
		activeTools.set(event.toolCallId, event.toolName);
		lastToolName = event.toolName;
		activity = `running ${event.toolName}`;
		if (event.toolName === "answer_questions") {
			pausedToolIds.add(event.toolCallId);
			pauseElapsed();
		}
		renderActive(ctx);
	});

	pi.on("tool_execution_end", (event, ctx) => {
		if (ctx.mode !== "tui") return;
		activeTools.delete(event.toolCallId);
		if (activeTools.size === 0) {
			lastToolName = undefined;
			activity = "waiting for provider after tool";
		} else {
			lastToolName = Array.from(activeTools.values()).at(-1);
			activity = `running ${lastToolName}`;
		}
		if (event.toolName === "answer_questions") {
			pausedToolIds.delete(event.toolCallId);
			if (pausedToolIds.size === 0) resumeElapsed();
		}
		renderActive(ctx);
	});

	pi.on("message_update", (event, ctx) => {
		if (ctx.mode !== "tui") return;
		if (event.message.role !== "assistant") return;
		if (event.assistantMessageEvent.type === "text_delta" && event.assistantMessageEvent.delta.length > 0) {
			const now = performance.now();
			firstTextDeltaAt ??= now;
			lastTextDeltaAt = now;
		}
		if (activity === "streaming response") return;
		activity = "streaming response";
		// The interval owns pulse rendering; update the title only on this transition.
		renderTitle(ctx);
	});

	pi.on("message_end", (event, ctx) => {
		if (ctx.mode !== "tui") return;
		if (event.message.role !== "assistant") return;
		latestTextStreamMetrics = calculateTextStreamMetrics({
			outputTokens: event.message.usage.output,
			reasoningTokens: event.message.usage.reasoning,
			requestStartedAt: providerRequestStartedAt,
			firstTextDeltaAt,
			lastTextDeltaAt,
			hasToolCalls: event.message.content.some((content) => content.type === "toolCall"),
		});
		providerRequestStartedAt = undefined;
	});

	pi.on("agent_end", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		finish(ctx);
	});

	pi.on("session_shutdown", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		resetToIdle(ctx);
	});
}
