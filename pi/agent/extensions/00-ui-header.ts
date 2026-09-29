import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { VERSION } from "@earendil-works/pi-coding-agent";

const RESET = "\x1b[0m";

type ThemeColor =
  | "thinkingOff"
  | "thinkingMinimal"
  | "thinkingLow"
  | "thinkingMedium"
  | "thinkingHigh"
  | "thinkingXhigh";

type Rgb = [number, number, number];

type HeaderTheme = {
  fg(color: ThemeColor, text: string): string;
  getFgAnsi(color: ThemeColor): string;
};

const THINKING_LEVEL_COLOR: Record<string, ThemeColor> = {
  off: "thinkingOff",
  minimal: "thinkingMinimal",
  low: "thinkingLow",
  medium: "thinkingMedium",
  high: "thinkingHigh",
  xhigh: "thinkingXhigh",
  max: "thinkingXhigh",
};

const HEADER_LEFT_PADDING = "  ";

const TITLE_LINES = [
  "███████████████     ",
  "███████████████     ",
  "█████     █████     ",
  "█████     █████     ",
  "██████████     █████",
  "██████████     █████",
  "█████          █████",
  "█████          █████",
  "                    "
];

const FALLBACK_COLORS: Record<ThemeColor, Rgb> = {
  thinkingOff: [238, 238, 238],
  thinkingMinimal: [187, 187, 187],
  thinkingLow: [0, 122, 204],
  thinkingMedium: [50, 92, 192],
  thinkingHigh: [122, 62, 157],
  thinkingXhigh: [230, 76, 230],
};

function mix(a: number, b: number, t: number) {
  return Math.round(a + (b - a) * t);
}

function mixRgb(a: Rgb, b: Rgb, t: number): Rgb {
  return [mix(a[0], b[0], t), mix(a[1], b[1], t), mix(a[2], b[2], t)];
}

function shade(color: Rgb, amount: number): Rgb {
  return amount < 0
    ? mixRgb(color, [0, 0, 0], Math.abs(amount))
    : mixRgb(color, [255, 255, 255], amount);
}

function fg([r, g, b]: Rgb, text: string) {
  return `\x1b[38;2;${r};${g};${b}m${text}${RESET}`;
}

function ansiToRgb(ansi: string): Rgb | undefined {
  const trueColor = ansi.match(/38;2;(\d+);(\d+);(\d+)/);
  if (trueColor) return [Number(trueColor[1]), Number(trueColor[2]), Number(trueColor[3])];

  const basic = ansi.match(/\x1b\[(3\d|9\d)m/);
  if (!basic) return undefined;
  const palette: Record<string, Rgb> = {
    "30": [0, 0, 0],
    "34": [0, 0, 238],
    "35": [205, 0, 205],
    "36": [0, 205, 205],
    "37": [229, 229, 229],
    "90": [127, 127, 127],
    "94": [92, 92, 255],
    "95": [255, 0, 255],
    "96": [0, 255, 255],
    "97": [255, 255, 255],
  };
  return palette[basic[1]];
}

function getThinkingPalette(theme: HeaderTheme, level: string | undefined) {
  const color = thinkingLevelColor(level);
  const themeBase = ansiToRgb(theme.getFgAnsi(color)) ?? FALLBACK_COLORS[color];
  const base = shade(themeBase, 0.12);

  // Keep the original header feel: one hue flowing darker → base → lighter → base.
  // The hue changes only when the thinking level changes; the base is slightly brighter
  // than the theme color so every thinking variant reads clearly in the header.
  return [
    shade(base, -0.38),
    shade(base, -0.14),
    shade(base, 0.24),
    shade(base, 0.44),
    shade(base, 0.24),
    shade(base, -0.14)
  ];
}

function sampleGradient(palette: Rgb[], position: number) {
  const wrapped = ((position % 1) + 1) % 1;
  const scaled = wrapped * palette.length;
  const index = Math.floor(scaled);
  const nextIndex = (index + 1) % palette.length;
  const t = scaled - index;
  const a = palette[index]!;
  const b = palette[nextIndex]!;
  return [mix(a[0], b[0], t), mix(a[1], b[1], t), mix(a[2], b[2], t)] as Rgb;
}

function thinkingLevelColor(level: string | undefined) {
  return THINKING_LEVEL_COLOR[level ?? ""] ?? "thinkingLow";
}

function gradientText(palette: Rgb[], text: string, phase: number) {
  const chars = [...text];
  const span = Math.max(chars.length - 1, 1);
  return chars
    .map((char, index) => {
      if (char === " ") return char;
      return fg(sampleGradient(palette, index / span + phase), char);
    })
    .join("");
}

function renderHeader(theme: HeaderTheme, _width: number, phase: number, thinkingLevel: string) {
  const palette = getThinkingPalette(theme, thinkingLevel);
  const lines = TITLE_LINES.map((line, row) => {
    const version = row === TITLE_LINES.length - 2
      ? theme.fg(thinkingLevelColor(thinkingLevel), ` v${VERSION}`)
      : "";
    return HEADER_LEFT_PADDING + gradientText(palette, line, phase + row * 0.045) + version;
  });
  return [
    "",
    ...lines,
    "",
  ];
}

export default function (pi: ExtensionAPI) {
  function installHeader(ctx: ExtensionContext) {
    // Keep the header palette stable for the lifetime of the session. Recoloring
    // all logo rows on every Shift+Tab forces a large top-of-screen repaint and
    // makes long sessions visibly jump. A reload/new session picks up the
    // currently selected thinking level.
    const headerThinkingLevel = pi.getThinkingLevel();
    ctx.ui.setHeader((tui, theme) => {
      let cachedLines: string[] | undefined;
      return {
        render(width: number) {
          return cachedLines ??= renderHeader(theme, width, 0, headerThinkingLevel);
        },
        invalidate() {
          cachedLines = undefined;
          tui.requestRender();
        },
      };
    });
  }

  pi.on("session_start", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    installHeader(ctx);
  });

  pi.on("session_shutdown", (_event, ctx) => {
    if (ctx.mode === "tui") ctx.ui.setHeader(undefined);
  });
}
