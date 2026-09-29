import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { EnvHttpProxyAgent, fetch as proxyFetch } from "undici";
import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";

const AUTH_PATH = join(homedir(), ".pi", "agent", "auth.json");
const REFRESH_INTERVAL_MS = 60_000;

type BalanceError = {
  message?: string;
  type?: string;
  code?: string | number;
};

type BalanceWithError = {
  error?: BalanceError;
};

type ProviderConfig<TBalance extends BalanceWithError> = {
  providerId: string;
  displayName: string;
  balanceUrl: string;
  statusId: string;
  command: string;
  commandDescription: string;
  isContext(ctx: ExtensionContext): boolean;
  formatBalance(data: TBalance): string;
  formatFooterBalance(ctx: Pick<ExtensionContext, "ui">, data: TBalance): string;
  httpError(status: number, statusText: string): TBalance;
};

type DeepSeekBalanceInfo = {
  currency?: string;
  total_balance?: string;
  granted_balance?: string;
  topped_up_balance?: string;
};

type DeepSeekBalanceResponse = BalanceWithError & {
  is_available?: boolean;
  balance_infos?: DeepSeekBalanceInfo[];
};

type OpenRouterBalanceResponse = BalanceWithError & {
  data?: {
    total_credits?: number;
    total_usage?: number;
  };
};

function getApiKey(providerId: string) {
  try {
    const data = JSON.parse(readFileSync(AUTH_PATH, "utf8")) as Record<string, any>;
    const credential = data?.[providerId];
    const key = credential?.key ?? credential?.apiKey ?? credential?.token;
    if (typeof key === "string" && key.length > 0) return key;
  } catch {
    // Missing or malformed auth file is handled by the caller.
  }

  return undefined;
}

// Глобальный fetch игнорирует HTTP(S)_PROXY, а прямой egress в этом окружении
// заблокирован; родной dispatcher из undici несовместим с встроенным fetch pi,
// поэтому используем fetch самого undici с EnvHttpProxyAgent (уважает NO_PROXY,
// при отсутствии прокси-переменных ходит напрямую).
const proxyDispatcher = new EnvHttpProxyAgent();

async function fetchBalance<TBalance extends BalanceWithError>(
  config: ProviderConfig<TBalance>,
  apiKey: string,
): Promise<TBalance> {
  const response = await proxyFetch(config.balanceUrl, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    dispatcher: proxyDispatcher,
  });

  let data: TBalance;
  try {
    data = (await response.json()) as TBalance;
  } catch {
    data = {} as TBalance;
  }

  if (!response.ok && !data.error?.message) {
    return config.httpError(response.status, response.statusText);
  }

  return data;
}

function createBalanceRefresher<TBalance extends BalanceWithError>(config: ProviderConfig<TBalance>) {
  let refreshTimer: ReturnType<typeof setInterval> | undefined;
  let activeContext: ExtensionContext | undefined;
  let lastBalance: TBalance | undefined;
  let inFlight = false;
  let queued = false;

  async function update(ctx: ExtensionContext): Promise<void> {
    if (!ctx.hasUI || !config.isContext(ctx)) return;

    const apiKey = getApiKey(config.providerId);
    if (!apiKey) {
      ctx.ui.setStatus(config.statusId, ctx.ui.theme.fg("warning", `set ${config.providerId} auth`));
      return;
    }

    if (inFlight) {
      queued = true;
      return;
    }

    inFlight = true;
    try {
      const balance = await fetchBalance(config, apiKey);
      if (!balance.error?.message) lastBalance = balance;
      if (activeContext !== ctx || !config.isContext(ctx)) return;
      ctx.ui.setStatus(config.statusId, config.formatFooterBalance(ctx, balance));
    } catch {
      if (activeContext !== ctx || !config.isContext(ctx)) return;
      ctx.ui.setStatus(config.statusId, ctx.ui.theme.fg("warning", `${config.providerId} balance unavailable`));
    } finally {
      inFlight = false;
      if (queued) {
        queued = false;
        void update(ctx);
      }
    }
  }

  return {
    refreshFor(ctx: ExtensionContext): void {
      activeContext = ctx;
      if (!ctx.hasUI || !config.isContext(ctx)) {
        ctx.ui.setStatus(config.statusId, undefined);
        return;
      }
      if (lastBalance) ctx.ui.setStatus(config.statusId, config.formatFooterBalance(ctx, lastBalance));
      void update(ctx);
    },
    remember(balance: TBalance): void {
      if (!balance.error?.message) lastBalance = balance;
    },
    start(): void {
      if (refreshTimer) clearInterval(refreshTimer);
      refreshTimer = setInterval(() => {
        if (activeContext) void update(activeContext);
      }, REFRESH_INTERVAL_MS);
      refreshTimer.unref?.();
    },
    stop(ctx?: ExtensionContext): void {
      if (refreshTimer) clearInterval(refreshTimer);
      refreshTimer = undefined;
      activeContext = undefined;
      ctx?.ui.setStatus(config.statusId, undefined);
    },
  };
}

function parseDeepSeekAmount(value: string | undefined) {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function formatDeepSeekAmount(currency: string | undefined, value: string | undefined) {
  const amount = parseDeepSeekAmount(value);
  const unit = currency ?? "balance";
  if (amount === undefined) return `${unit} ${value ?? "unknown"}`;
  if (currency === "USD") return `$${amount.toFixed(2)}`;
  return `${amount.toFixed(2)} ${unit}`;
}

function formatDeepSeekBalanceInfo(info: DeepSeekBalanceInfo) {
  const currency = info.currency ?? "unknown";
  const total = info.total_balance ?? "unknown";
  const granted = info.granted_balance ?? "unknown";
  const toppedUp = info.topped_up_balance ?? "unknown";

  return `${currency}: total ${total}, granted ${granted}, topped up ${toppedUp}`;
}

function formatOpenRouterAmount(value: number | undefined) {
  if (value === undefined) return "unknown";
  return `$${value.toFixed(2)}`;
}

const deepSeekConfig: ProviderConfig<DeepSeekBalanceResponse> = {
  providerId: "deepseek",
  displayName: "DeepSeek",
  balanceUrl: "https://api.deepseek.com/user/balance",
  statusId: "deepseek-balance",
  command: "deepseek:balance",
  commandDescription: "Check DeepSeek API balance using ~/.pi/agent/auth.json",
  isContext(ctx) {
    return ctx.model?.provider === "deepseek";
  },
  formatBalance(data) {
    if (data.error?.message) {
      const type = data.error.type ? ` (${data.error.type})` : "";
      return `DeepSeek balance error${type}: ${data.error.message}`;
    }

    const availability =
      typeof data.is_available === "boolean"
        ? data.is_available
          ? "available"
          : "not available"
        : "availability unknown";

    const balances = data.balance_infos?.length
      ? data.balance_infos.map(formatDeepSeekBalanceInfo).join("\n")
      : "No balance rows returned.";

    return `DeepSeek account: ${availability}\n${balances}`;
  },
  formatFooterBalance(ctx, data) {
    const theme = ctx.ui.theme;

    if (data.error?.message) return theme.fg("warning", "deepseek balance unavailable");
    if (data.is_available === false) return theme.fg("warning", "unavailable");

    const balances = data.balance_infos ?? [];
    const preferred = balances.find((info) => info.currency === "USD") ?? balances[0];
    if (!preferred) return theme.fg("warning", "deepseek balance unavailable");

    return theme.fg("success", formatDeepSeekAmount(preferred.currency, preferred.total_balance));
  },
  httpError(status, statusText) {
    return { error: { message: `HTTP ${status} ${statusText}`.trim() } };
  },
};

const openRouterConfig: ProviderConfig<OpenRouterBalanceResponse> = {
  providerId: "openrouter",
  displayName: "OpenRouter",
  balanceUrl: "https://openrouter.ai/api/v1/credits",
  statusId: "openrouter-balance",
  command: "openrouter:balance",
  commandDescription: "Check OpenRouter API balance using ~/.pi/agent/auth.json",
  isContext(ctx) {
    return ctx.model?.provider === "openrouter";
  },
  formatBalance(data) {
    if (data.error?.message) {
      return `OpenRouter balance error: ${data.error.message}`;
    }

    const credits = data.data?.total_credits;
    const usage = data.data?.total_usage;

    if (credits === undefined) {
      return "OpenRouter: no balance data available";
    }

    const remaining = credits - (usage ?? 0);
    return `OpenRouter: ${formatOpenRouterAmount(remaining)} remaining (credits: ${formatOpenRouterAmount(credits)}, used: ${formatOpenRouterAmount(usage)})`;
  },
  formatFooterBalance(ctx, data) {
    const theme = ctx.ui.theme;

    if (data.error?.message) return theme.fg("warning", "openrouter balance unavailable");

    const credits = data.data?.total_credits;
    const usage = data.data?.total_usage;

    if (credits === undefined) return theme.fg("warning", "openrouter balance unavailable");

    const remaining = credits - (usage ?? 0);
    return theme.fg("success", formatOpenRouterAmount(remaining));
  },
  httpError(status, statusText) {
    return { error: { message: `HTTP ${status} ${statusText}`.trim(), code: status } };
  },
};

function registerProviderBalance<TBalance extends BalanceWithError>(
  pi: ExtensionAPI,
  config: ProviderConfig<TBalance>,
) {
  const refresher = createBalanceRefresher(config);

  pi.on("session_start", (_event, ctx) => {
    refresher.start();
    refresher.refreshFor(ctx);
  });

  pi.on("turn_end", (_event, ctx) => {
    refresher.refreshFor(ctx);
  });

  pi.on("model_select", (_event, ctx) => {
    refresher.refreshFor(ctx);
  });

  pi.on("session_shutdown", (_event, ctx) => {
    refresher.stop(ctx);
  });

  pi.registerCommand(config.command, {
    description: config.commandDescription,
    handler: async (_args, ctx) => {
      const apiKey = getApiKey(config.providerId);
      if (!apiKey) {
        ctx.ui.notify(
          `Set ${config.providerId}.key in ~/.pi/agent/auth.json to check ${config.displayName} balance`,
          "error",
        );
        return;
      }

      try {
        const balance = await fetchBalance(config, apiKey);
        refresher.remember(balance);
        ctx.ui.notify(config.formatBalance(balance), balance.error ? "error" : "info");
        if (ctx.hasUI && config.isContext(ctx)) {
          ctx.ui.setStatus(config.statusId, config.formatFooterBalance(ctx, balance));
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        ctx.ui.notify(`${config.displayName} balance request failed: ${message}`, "error");
      }
    },
  });
}

export default function balanceExtension(pi: ExtensionAPI) {
  registerProviderBalance(pi, deepSeekConfig);
  registerProviderBalance(pi, openRouterConfig);
}
