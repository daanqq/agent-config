type QuotaWindow = {
  label: "5h" | "7d" | "30d";
  usedPercent: number;
  remainingPercent: number;
  resetsAt: Date;
  windowSeconds: number;
};

function parseDateish(value: unknown): Date {
  if (typeof value === "number") return new Date(value > 10 ** 11 ? value : value * 1000);
  if (typeof value === "string") return new Date(value);
  return new Date(0);
}

function percentLeftToUsedPercent(limit: any): number | undefined {
  const remaining = limit?.percent_left ?? limit?.remaining_percent;
  if (remaining != null) {
    const value = Number(remaining);
    return Number.isFinite(value) && value >= 0 && value <= 100 ? 100 - value : undefined;
  }
  if (limit?.used_percent != null) {
    const value = Number(limit.used_percent);
    return Number.isFinite(value) && value >= 0 && value <= 100 ? value : undefined;
  }
  // An object without a known percentage field is not an unused window.
  // Treating it as used_percent=0 used to produce a fabricated 100% footer.
  return undefined;
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function quotaWindowLabel(window: any, fallback: QuotaWindow["label"]): QuotaWindow["label"] {
  const seconds = Number(window?.limit_window_seconds ?? 0);
  if (Number.isFinite(seconds) && seconds > 0) {
    if (seconds >= 20 * 24 * 60 * 60) return "30d";
    if (seconds >= 6 * 24 * 60 * 60) return "7d";
    return "5h";
  }

  // Free accounts may expose only a long reset time without
  // limit_window_seconds.  Classify that single window by its reset horizon so
  // it is not mislabeled as a 5h quota.
  const reset = parseDateish(window?.reset_at ?? window?.reset_time_ms).getTime();
  const diffSeconds = (reset - Date.now()) / 1000;
  if (Number.isFinite(diffSeconds) && diffSeconds > 0) {
    if (diffSeconds >= 20 * 24 * 60 * 60) return "30d";
    if (diffSeconds >= 6 * 24 * 60 * 60) return "7d";
  }
  return fallback;
}

export function parseCodexWindows(data: any): QuotaWindow[] {
  const rateLimit = data?.rate_limit ?? data?.rate_limits ?? {};
  const primary = rateLimit.primary_window ?? rateLimit.primary ?? rateLimit.five_hour_limit ?? rateLimit.five_hour;
  const secondary =
    rateLimit.secondary_window ??
    rateLimit.secondary ??
    rateLimit.weekly_limit ??
    rateLimit.weekly ??
    rateLimit.monthly_limit ??
    rateLimit.monthly ??
    rateLimit.thirty_day_limit ??
    rateLimit.thirty_day;
  const windows: QuotaWindow[] = [];

  if (primary) {
    const usedPercent = percentLeftToUsedPercent(primary);
    if (usedPercent != null) {
      const label = quotaWindowLabel(primary, "5h");
      windows.push({
        label,
        usedPercent,
        remainingPercent: clampPercent(100 - usedPercent),
        resetsAt: parseDateish(primary.reset_at ?? primary.reset_time_ms),
        windowSeconds: Number(primary.limit_window_seconds ?? (label === "30d" ? 30 * 24 * 60 * 60 : label === "7d" ? 7 * 24 * 60 * 60 : 5 * 60 * 60)),
      });
    }
  }

  if (secondary) {
    const usedPercent = percentLeftToUsedPercent(secondary);
    if (usedPercent != null) {
      const label = quotaWindowLabel(secondary, "7d");
      windows.push({
        label,
        usedPercent,
        remainingPercent: clampPercent(100 - usedPercent),
        resetsAt: parseDateish(secondary.reset_at ?? secondary.reset_time_ms),
        windowSeconds: Number(secondary.limit_window_seconds ?? (label === "30d" ? 30 : 7) * 24 * 60 * 60),
      });
    }
  }

  return windows;
}

export function resetText(date: Date, now = Date.now()): string {
  const diffMs = date.getTime() - now;
  if (!Number.isFinite(diffMs) || date.getTime() <= 0) return "unknown";
  if (diffMs <= 0) return "now";
  const minutes = Math.ceil(diffMs / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  if (hours < 24) return restMinutes > 0 ? `${hours}h${restMinutes}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours > 0 ? `${days}d${restHours}h` : `${days}d`;
}
