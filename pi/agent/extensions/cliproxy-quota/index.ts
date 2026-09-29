import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { fetchSharedPoolQuota, formatPoolDetails, formatPoolFooter, type PoolQuota } from "./quota.ts";

const EXTENSION_ID = "cliproxy-quota";
const CLI_PROXY_PROVIDERS = new Set(["cliproxy", "openai-codex"]);
const REFRESH_MS = 60_000;

export function isCLIProxyProvider(provider: string | undefined): boolean {
	return provider !== undefined && CLI_PROXY_PROVIDERS.has(provider);
}

function isCLIProxyModel(ctx: ExtensionContext | ExtensionCommandContext): boolean {
	return isCLIProxyProvider(ctx.model?.provider);
}

export default function cliproxyQuotaExtension(pi: ExtensionAPI) {
	let activeContext: ExtensionContext | undefined;
	let timer: ReturnType<typeof setInterval> | undefined;
	let refreshInFlight: Promise<PoolQuota> | undefined;
	let lastPool: PoolQuota | undefined;
	let selectedProvider: string | undefined;

	function clearStatus(ctx: ExtensionContext | ExtensionCommandContext): void {
		if (ctx.hasUI) ctx.ui.setStatus(EXTENSION_ID, undefined);
	}

	function render(ctx: ExtensionContext | ExtensionCommandContext, pool: PoolQuota, provider = ctx.model?.provider): void {
		if (!ctx.hasUI || provider !== selectedProvider || !isCLIProxyProvider(provider)) {
			clearStatus(ctx);
			return;
		}
		ctx.ui.setStatus(EXTENSION_ID, formatPoolFooter(pool));
	}

	async function load(): Promise<PoolQuota> {
		if (refreshInFlight) return refreshInFlight;
		refreshInFlight = fetchSharedPoolQuota().finally(() => {
			refreshInFlight = undefined;
		});
		return refreshInFlight;
	}

	async function refresh(ctx: ExtensionContext, provider = ctx.model?.provider): Promise<void> {
		if (ctx !== activeContext || provider !== selectedProvider || !isCLIProxyProvider(provider)) {
			clearStatus(ctx);
			return;
		}
		try {
			lastPool = await load();
			if (ctx === activeContext) render(ctx, lastPool, provider);
		} catch {
			if (ctx === activeContext && isCLIProxyModel(ctx)) {
				ctx.ui.setStatus(EXTENSION_ID, "quota unavailable");
			}
		}
	}

	pi.registerCommand("cliproxy:quota", {
		description: "Show combined Codex quota for CLIProxyAPI accounts",
		handler: async (_args, ctx) => {
			try {
				lastPool = await load();
				render(ctx, lastPool);
				ctx.ui.notify(formatPoolDetails(lastPool), lastPool.errors.length > 0 ? "warning" : "info");
			} catch (error) {
				ctx.ui.notify(`CLIProxyAPI quota unavailable: ${error instanceof Error ? error.message : String(error)}`, "error");
			}
		},
	});

	pi.registerCommand("statuses", {
		description: "Show quota status for every CLIProxyAPI Codex subscription",
		handler: async (_args, ctx) => {
			try {
				lastPool = await load();
				render(ctx, lastPool);
				ctx.ui.notify(ctx.ui.theme.fg("dim", formatPoolDetails(lastPool)), lastPool.errors.length > 0 ? "warning" : "info");
			} catch (error) {
				ctx.ui.notify(`CLIProxyAPI quota unavailable: ${error instanceof Error ? error.message : String(error)}`, "error");
			}
		},
	});

	pi.on("session_start", (_event, ctx) => {
		activeContext = ctx;
		selectedProvider = ctx.model?.provider;
		if (timer) clearInterval(timer);
		timer = setInterval(() => void refresh(ctx, selectedProvider), REFRESH_MS);
		timer.unref?.();
		if (isCLIProxyModel(ctx)) void refresh(ctx);
		else clearStatus(ctx);
	});

	pi.on("model_select", (event, ctx) => {
		const provider = event.model.provider;
		selectedProvider = provider;
		if (!isCLIProxyProvider(provider)) {
			clearStatus(ctx);
			return;
		}
		const uiContext = activeContext ?? ctx;
		if (lastPool) render(uiContext, lastPool, provider);
		void refresh(uiContext, provider);
	});

	pi.on("session_shutdown", (_event, ctx) => {
		if (timer) clearInterval(timer);
		timer = undefined;
		activeContext = undefined;
		selectedProvider = undefined;
		refreshInFlight = undefined;
		clearStatus(ctx);
	});
}
