import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BEGIN_SYNCHRONIZED_OUTPUT = "\x1b[?2026h";
const END_SYNCHRONIZED_OUTPUT = "\x1b[?2026l";
const RELEASE_DELAY_MS = 32;
const FALLBACK_TIMEOUT_MS = 2000;

type Timer = ReturnType<typeof setTimeout>;

type SynchronizedOutputState = {
  active: boolean;
  fallbackTimer: Timer | undefined;
  releaseTimer: Timer | undefined;
  exitHookInstalled: boolean;
  writeHookInstalled: boolean;
  originalWrite: typeof process.stdout.write | undefined;
};

declare global {
  var __piSynchronizedOutputState: SynchronizedOutputState | undefined;
}

function getState(): SynchronizedOutputState {
  return globalThis.__piSynchronizedOutputState ??= {
    active: false,
    fallbackTimer: undefined,
    releaseTimer: undefined,
    exitHookInstalled: false,
    writeHookInstalled: false,
    originalWrite: undefined,
  };
}

function clearTimer(timer: Timer | undefined): undefined {
  if (timer) clearTimeout(timer);
  return undefined;
}

function writeSequence(sequence: string): boolean {
  if (!process.stdout.isTTY) return false;
  try {
    const write = getState().originalWrite ?? process.stdout.write;
    Reflect.apply(write, process.stdout, [sequence]);
    return true;
  } catch {
    return false;
  }
}

function installWriteHook(): void {
  const state = getState();
  if (state.writeHookInstalled) return;

  const stdout = process.stdout;
  const originalWrite = stdout.write;
  state.originalWrite = originalWrite;
  state.writeHookInstalled = true;

  const patchedWrite = function (
    this: typeof stdout,
    chunk: string | Uint8Array,
    ...args: unknown[]
  ): boolean {
    let nextChunk = chunk;
    if (getState().active) {
      if (typeof chunk === "string") {
        nextChunk = chunk.replaceAll(END_SYNCHRONIZED_OUTPUT, "");
      } else if (Buffer.isBuffer(chunk)) {
        const endSequence = Buffer.from(END_SYNCHRONIZED_OUTPUT);
        if (chunk.includes(endSequence)) {
          nextChunk = Buffer.from(chunk.toString().replaceAll(END_SYNCHRONIZED_OUTPUT, ""));
        }
      }
    }
    return Reflect.apply(originalWrite, this, [nextChunk, ...args]) as boolean;
  } as typeof stdout.write;

  stdout.write = patchedWrite;
}

function endSynchronizedOutput(): void {
  const state = getState();
  state.fallbackTimer = clearTimer(state.fallbackTimer);
  state.releaseTimer = clearTimer(state.releaseTimer);
  if (!state.active) return;

  state.active = false;
  writeSequence(END_SYNCHRONIZED_OUTPUT);
}

function beginSynchronizedOutput(): void {
  const state = getState();
  state.fallbackTimer = clearTimer(state.fallbackTimer);
  state.releaseTimer = clearTimer(state.releaseTimer);

  if (!state.active && !writeSequence(BEGIN_SYNCHRONIZED_OUTPUT)) return;
  state.active = true;

  // If replacement fails before resource discovery, do not leave the
  // terminal indefinitely holding buffered frames.
  state.fallbackTimer = setTimeout(endSynchronizedOutput, FALLBACK_TIMEOUT_MS);
  state.fallbackTimer.unref();
}

function scheduleSynchronizedOutputRelease(): void {
  const state = getState();
  if (!state.active) return;

  state.releaseTimer = clearTimer(state.releaseTimer);
  // Resource discovery starts only after every session_start handler has
  // settled. Give the TUI one frame to paint the fully rebound session before
  // exposing buffered output.
  state.releaseTimer = setTimeout(endSynchronizedOutput, RELEASE_DELAY_MS);
  state.releaseTimer.unref();
}

export default function synchronizedUiTransitionExtension(pi: ExtensionAPI) {
  const state = getState();
  installWriteHook();
  if (!state.exitHookInstalled) {
    state.exitHookInstalled = true;
    process.once("exit", endSynchronizedOutput);
  }

  pi.on("session_shutdown", (event, ctx) => {
    if (ctx.mode !== "tui") return;
    if (event.reason === "new" || event.reason === "resume" || event.reason === "fork") {
      beginSynchronizedOutput();
    }
  });

  pi.on("resources_discover", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    scheduleSynchronizedOutputRelease();
  });
}
