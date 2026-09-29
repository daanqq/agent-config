import { createHash } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BRACKETED_PASTE_START = "\x1b[200~";
const BRACKETED_PASTE_END = "\x1b[201~";
const DOUBLE_PASTE_WINDOW_MS = 3_000;
const LONG_PASTE_MAX_LINES = 10;
const LONG_PASTE_MAX_CHARS = 1_000;

type Candidate = {
  pasteFingerprint: string;
  editorFingerprint: string;
  armedAt: number;
};

function extractBracketedPaste(data: string): string | undefined {
  if (
    !data.startsWith(BRACKETED_PASTE_START) ||
    !data.endsWith(BRACKETED_PASTE_END)
  ) {
    return undefined;
  }

  return data.slice(BRACKETED_PASTE_START.length, -BRACKETED_PASTE_END.length);
}

function normalizePaste(text: string): string {
  const decoded = text.replace(/\x1b\[(\d+);5u/g, (match, code: string) => {
    const codePoint = Number(code);
    if (codePoint >= 97 && codePoint <= 122) {
      return String.fromCharCode(codePoint - 96);
    }
    if (codePoint >= 65 && codePoint <= 90) {
      return String.fromCharCode(codePoint - 64);
    }
    return match;
  });

  return decoded
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\t/g, "    ")
    .split("")
    .filter((character) => character === "\n" || character.charCodeAt(0) >= 32)
    .join("");
}

function isLongPaste(text: string): boolean {
  return (
    text.split("\n").length > LONG_PASTE_MAX_LINES ||
    text.length > LONG_PASTE_MAX_CHARS
  );
}

function fingerprint(text: string): string {
  return createHash("sha256").update(text).digest("hex");
}

export default function piPaste(pi: ExtensionAPI): void {
  let unsubscribe: (() => void) | undefined;

  pi.on("session_start", (_event, ctx) => {
    if (ctx.mode !== "tui") return;

    unsubscribe?.();

    let candidate: Candidate | undefined;
    let armGeneration = 0;
    let warned = false;

    const warnOnce = () => {
      if (warned) return;
      warned = true;
      try {
        ctx.ui.notify(
          "Could not expand pasted text; Pi's normal paste behavior was preserved.",
          "warning",
        );
      } catch {
        // Notifications must never interfere with terminal input.
      }
    };

    unsubscribe = ctx.ui.onTerminalInput((data) => {
      const rawPaste = extractBracketedPaste(data);
      if (rawPaste === undefined) return undefined;

      const normalizedPaste = normalizePaste(rawPaste);
      if (!isLongPaste(normalizedPaste)) return undefined;

      const pasteFingerprint = fingerprint(normalizedPaste);
      const observedAt = Date.now();

      if (candidate && observedAt - candidate.armedAt > DOUBLE_PASTE_WINDOW_MS) {
        candidate = undefined;
      }

      if (candidate?.pasteFingerprint === pasteFingerprint) {
        try {
          const editorText = ctx.ui.getEditorText();
          if (fingerprint(editorText) === candidate.editorFingerprint) {
            ctx.ui.setEditorText(editorText);
            candidate = undefined;
            armGeneration += 1;
            try {
              ctx.ui.notify("Paste expanded.", "info");
            } catch {
              // Notifications must never interfere with terminal input.
            }
            return { consume: true };
          }
        } catch {
          candidate = undefined;
          warnOnce();
          return undefined;
        }
      }

      let editorTextBeforePaste: string;
      try {
        editorTextBeforePaste = ctx.ui.getEditorText();
      } catch {
        candidate = undefined;
        warnOnce();
        return undefined;
      }

      const generation = ++armGeneration;
      queueMicrotask(() => {
        if (generation !== armGeneration) return;

        try {
          const editorTextAfterPaste = ctx.ui.getEditorText();
          if (editorTextAfterPaste === editorTextBeforePaste) return;

          candidate = {
            pasteFingerprint,
            editorFingerprint: fingerprint(editorTextAfterPaste),
            armedAt: Date.now(),
          };
        } catch {
          candidate = undefined;
        }
      });

      return undefined;
    });
  });

  pi.on("session_shutdown", () => {
    unsubscribe?.();
    unsubscribe = undefined;
  });
}
