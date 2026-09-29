/**
 * video-analysis — глобальное расширение pi: инструмент analyze_video.
 *
 * Основная модель (Sol/Luna) вызывает analyze_video, когда для задачи нужно
 * содержимое видео. Видео уходит в GLM-5.3-Flash через CLI-скрипт
 * ~/video-analyze/video-analyze.mjs (OpenRouter), текстовый отчёт
 * возвращается как обычный toolResult.
 *
 * Основной путь — раскадровка с вжжёнными таймкодами (frames): на коротких
 * роликах она даёт более точные таймстампы, чем нативный видео-вход
 * (проверено в прототипе, см. ~/video-analyze/).
 */

import { statSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join } from "node:path";
import { Type } from "typebox";
import { StringEnum } from "@earendil-works/pi-ai";
import { truncateHead, DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES } from "@earendil-works/pi-coding-agent";

const SCRIPT = join(homedir(), "video-analyze", "video-analyze.mjs");
const FRAME_CAP = 36; // максимум кадров в одном тайл-листе (см. скрипт)

function fmtSec(s) {
  if (s == null || Number.isNaN(s)) return "?";
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return m > 0 ? `${m}:${sec.toFixed(1).padStart(4, "0")}` : `${sec.toFixed(1)}s`;
}

function formatReport(out) {
  const { meta, usage, report } = out;
  const lines = [];
  if (meta.frames) {
    lines.push(`[video] ${meta.source}`);
    lines.push(`mode: frames ${meta.frames.fps}fps, ${meta.frames.count} frames (${meta.frames.grid}), timestamps from ${fmtSec(meta.frames.timestampOrigin)}`);
  } else {
    lines.push(`[video] ${meta.source}${meta.durationSec != null ? `, ${fmtSec(meta.durationSec)}` : ""}`);
    lines.push(`mode: native video input`);
  }
  lines.push("");
  if (report.parseError) {
    lines.push(`(unparsed model output)`);
    lines.push(report.raw ?? "");
  } else {
    if (report.summary) lines.push(`Summary: ${report.summary}`, "");
    for (const o of report.observations ?? []) {
      const conf = o.confidence != null ? ` (${Math.round(o.confidence * 100)}%)` : "";
      lines.push(`  [${fmtSec(o.startSec)}–${fmtSec(o.endSec)}]${conf} ${o.observation}`);
    }
    if (report.visibleText?.length) {
      lines.push("", "Visible text:");
      for (const t of report.visibleText) lines.push(`  [${fmtSec(t.startSec)}] ${t.text}`);
    }
    if (report.uncertainties?.length) {
      lines.push("", "Uncertainties:");
      for (const u of report.uncertainties) lines.push(`  • ${u}`);
    }
    if (report.suggestedFollowUps?.length) {
      lines.push("", "Suggested follow-ups:");
      for (const f of report.suggestedFollowUps) lines.push(`  → ${f}`);
    }
  }
  lines.push(
    "",
    `[nested model: ${meta.model}, ${usage.prompt_tokens ?? "?"} in / ${usage.completion_tokens ?? "?"} out tokens, cost $${(usage.cost ?? 0).toFixed(6)}]`,
  );
  return lines.join("\n");
}

export default function (pi: ExtensionAPI) {
  // Подтверждение на каждый локальный файл — один раз за сессию
  const approved = new Set<string>();

  pi.registerTool({
    name: "analyze_video",
    label: "Analyze Video",
    description:
      "Analyze a local or remote video (screen recordings, UI demos, bug reproductions, motion) " +
      "with a video-capable model (GLM-5.3-Flash). Returns timestamped observations, visible text (OCR) " +
      "and uncertainties. Use it when conclusions depend on what happens in a video file. " +
      "Timestamps in the report are absolute if startSec is 0/omitted; otherwise they are shifted back by startSec. " +
      `Frames mode covers up to ${FRAME_CAP} frames per sheet; for long videos analyze startSec/endSec windows.`,
    promptSnippet: "Analyze a video file through a dedicated video-capable model",
    promptGuidelines: [
      "Use analyze_video when a task depends on the content of a video (screen recording, demo, bug reproduction).",
      "Pass a focused question in `task` describing which observable facts are needed; do not request a generic summary.",
      "For videos longer than ~9 seconds at default fps, set startSec/endSec to analyze windows, or lower fps.",
    ],
    parameters: Type.Object({
      source: Type.String({ description: "Path to a local video file or http(s) URL" }),
      task: Type.String({ description: "Focused research question: which observable facts are needed" }),
      startSec: Type.Optional(Type.Number({ description: "Analyze from this second (clip start)" })),
      endSec: Type.Optional(Type.Number({ description: "Analyze up to this second (clip end)" })),
      mode: Type.Optional(
        StringEnum(["frames", "video"] as const, {
          description: "frames = contact sheet with burned-in timecodes (default, most accurate); video = native video input",
        }),
      ),
      fps: Type.Optional(Type.Number({ description: "Frames per second for frames mode. Default 4" })),
    }),

    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const mode = params.mode ?? "frames";
      const isUrl = /^https?:\/\//.test(params.source);

      let abs = params.source;
      let sizeDesc = "";
      if (!isUrl) {
        abs = params.source.startsWith("~")
          ? join(homedir(), params.source.slice(1))
          : isAbsolute(params.source)
            ? params.source
            : join(ctx.cwd, params.source);
        let sizeBytes;
        try {
          sizeBytes = statSync(abs).size;
        } catch {
          throw new Error(`Video file not found: ${abs}`);
        }
        sizeDesc = `, ${(sizeBytes / 1024).toFixed(0)}KB`;
        // Локальный файл покидает машину — подтверждение один раз на файл за сессию
        if (ctx.hasUI && !approved.has(abs)) {
          const ok = await ctx.ui.confirm(
            "Send video to external model?",
            `${abs}${sizeDesc}\n\nThe file will be uploaded to ${mode === "video" ? "OpenRouter (DeepInfra)" : "OpenRouter"} as base64 for GLM-5.3-Flash analysis.`,
          );
          if (!ok) {
            return { content: [{ type: "text", text: "Cancelled: user did not approve sending this video." }], details: { cancelled: true } };
          }
        }
        approved.add(abs);
      }

      const args = [abs, "--json", "--question", params.task];
      if (params.startSec != null) args.push("--start", String(params.startSec));
      if (params.endSec != null) args.push("--end", String(params.endSec));
      if (mode === "frames") {
        args.push("--frames", String(params.fps ?? 4));
      } else {
        // Нативный видео-вход стабильно работает только у DeepInfra
        args.push("--provider", "DeepInfra");
      }

      const result = await pi.exec("node", [SCRIPT, ...args], { signal, timeout: 300_000 });
      if (result.code !== 0) {
        throw new Error(`video-analyze failed (exit ${result.code}): ${result.stderr.slice(-1500) || result.stdout.slice(-500)}`);
      }

      let out;
      try {
        out = JSON.parse(result.stdout);
      } catch {
        throw new Error(`video-analyze returned non-JSON output: ${result.stdout.slice(0, 500)}`);
      }

      // В frames-режиме таймкоды считаются от начала клипа — возвращаем абсолютные
      if (mode === "frames" && params.startSec != null && out.report && !out.report.parseError) {
        const shift = (v) => (typeof v === "number" ? v + params.startSec : v);
        for (const o of out.report.observations ?? []) {
          o.startSec = shift(o.startSec);
          o.endSec = shift(o.endSec);
        }
        for (const t of out.report.visibleText ?? []) t.startSec = shift(t.startSec);
      }

      const text = formatReport(out);
      const truncation = truncateHead(text, { maxLines: DEFAULT_MAX_LINES, maxBytes: DEFAULT_MAX_BYTES });

      return {
        content: [
          {
            type: "text",
            text: truncation.truncated
              ? `${truncation.content}\n\n[Report truncated to ${truncation.outputLines}/${truncation.totalLines} lines]`
              : text,
          },
        ],
        details: { meta: out.meta, usage: out.usage, report: out.report },
        usage: {
          // Nested-вызов GLM: стоимость целиком в input, split по токенам недоступен
          input: out.usage?.prompt_tokens ?? 0,
          output: out.usage?.completion_tokens ?? 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: out.usage?.total_tokens ?? 0,
          cost: { input: out.usage?.cost ?? 0, output: 0, cacheRead: 0, cacheWrite: 0, total: out.usage?.cost ?? 0 },
        },
      };
    },
  });
}
