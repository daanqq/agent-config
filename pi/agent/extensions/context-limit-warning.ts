import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const FALLBACK_THRESHOLD_TOKENS = 128_000;

function getThreshold(contextWindow?: number): number {
  return contextWindow ? contextWindow / 2 : FALLBACK_THRESHOLD_TOKENS;
}

function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) {
    const thousands = tokens / 1_000;
    return `${Number.isInteger(thousands) ? thousands : thousands.toFixed(1)}k`;
  }
  return String(Math.round(tokens));
}

export default function (pi: ExtensionAPI) {
  pi.on("agent_end", async (_event, ctx) => {
    if (!ctx.hasUI) return;

    const usage = ctx.getContextUsage();
    if (!usage) return;

    const threshold = getThreshold(usage.contextWindow ?? ctx.model?.contextWindow);
    const isAboveThreshold = usage.tokens > threshold;
    if (!isAboveThreshold) return;

    ctx.ui.notify(
      `Context usage is above ${formatTokens(threshold)}. Consider /shake, /compact or /new.`,
      "warning",
    );
  });
}
