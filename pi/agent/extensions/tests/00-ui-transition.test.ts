import assert from "node:assert/strict";
import test from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import synchronizedUiTransitionExtension from "../00-ui-00-transition.ts";

const BEGIN_SYNCHRONIZED_OUTPUT = "\x1b[?2026h";
const END_SYNCHRONIZED_OUTPUT = "\x1b[?2026l";

type Handler = (event: Record<string, unknown>, ctx: { mode: string }) => unknown;

test("keeps replacement output buffered until resource discovery", async () => {
  const handlers = new Map<string, Handler>();
  const writes: string[] = [];
  const originalWrite = process.stdout.write;
  const originalIsTty = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");

  Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: true });
  process.stdout.write = ((chunk: string | Uint8Array) => {
    writes.push(typeof chunk === "string" ? chunk : Buffer.from(chunk).toString());
    return true;
  }) as typeof process.stdout.write;

  try {
    const pi = {
      on(event: string, handler: Handler) {
        handlers.set(event, handler);
      },
    } as unknown as ExtensionAPI;
    synchronizedUiTransitionExtension(pi);

    const ctx = { mode: "tui" };
    await handlers.get("session_shutdown")?.({ reason: "resume" }, ctx);
    await handlers.get("session_start")?.({ reason: "resume" }, ctx);
    await delay(50);

    assert.equal(writes.join("").includes(BEGIN_SYNCHRONIZED_OUTPUT), true);
    assert.equal(writes.join("").includes(END_SYNCHRONIZED_OUTPUT), false);

    await handlers.get("resources_discover")?.({ reason: "startup" }, ctx);
    await delay(50);

    assert.equal(writes.join("").includes(END_SYNCHRONIZED_OUTPUT), true);
  } finally {
    process.stdout.write = originalWrite;
    if (originalIsTty) Object.defineProperty(process.stdout, "isTTY", originalIsTty);
    else delete (process.stdout as { isTTY?: boolean }).isTTY;
    globalThis.__piSynchronizedOutputState = undefined;
  }
});
