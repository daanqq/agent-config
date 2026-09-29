import assert from "node:assert/strict";
import test from "node:test";
import type { Theme } from "@earendil-works/pi-coding-agent";
import type { Cause, Scope } from "effect";
import { Effect, Layer, ManagedRuntime, Queue, Stream } from "effect";
import { BackendRegistry, type SessionCheckpoint, type SubagentBackend, type SubagentSession } from "./src/backend.ts";
import { SendError, SpawnError, type SpawnTask, type SubagentEvent } from "./src/domain.ts";
import { MAX_IDLE_BACKENDS, MAX_TRACKED, SubagentManager, SubagentManagerLive } from "./src/manager.ts";
import { buildTranscriptLines, CompletedTranscriptCache } from "./src/ui/transcript.ts";

const task: SpawnTask = {
  title: "performance test", prompt: "initial", cwd: process.cwd(),
  parent: { parentCwd: process.cwd(), projectTrusted: false },
};
const tick = () => new Promise<void>((resolve) => setImmediate(resolve));
const gate = () => Promise.withResolvers<void>();

interface Transport {
  id: string;
  active: boolean;
  closed: boolean;
  persistent: boolean;
  sent: string[];
  emit(event: SubagentEvent): void;
  finish(text?: string): void;
  end(): void;
}

async function harness() {
  const transports: Transport[] = [];
  const resumed: SessionCheckpoint[] = [];
  const controls: {
    resumeGate?: Promise<void>;
    closeGate?: Promise<void>;
    sendGate?: Promise<void>;
    failResume?: boolean;
    failSend?: boolean;
  } = {};
  let serial = 0;
  let opening = 0;
  let closing = 0;
  const make = (checkpoint?: SessionCheckpoint): Effect.Effect<SubagentSession, SpawnError, Scope.Scope> =>
    Effect.gen(function* () {
      if (checkpoint) {
        resumed.push(checkpoint);
        opening++;
        yield* Effect.addFinalizer(() => Effect.sync(() => { opening--; }));
        if (controls.resumeGate) yield* Effect.promise(() => controls.resumeGate!);
        if (controls.failResume) return yield* new SpawnError({ message: "resume failed" });
      }
      const events = yield* Queue.make<SubagentEvent, Cause.Done>();
      const transport: Transport = {
        id: checkpoint?.nativeSessionId ?? `native-${++serial}`,
        active: !checkpoint, closed: false, persistent: true, sent: [],
        emit: (event) => { Queue.offerUnsafe(events, event); },
        finish: (text = "answer") => {
          transport.active = false;
          transport.emit({ _tag: "AssistantMessage", parts: [{ type: "text", text }] });
          transport.emit({ _tag: "RunSettled", outcome: { _tag: "Completed", finalText: text } });
        },
        end: () => { transport.active = false; Queue.endUnsafe(events); },
      };
      transports.push(transport);
      yield* Effect.addFinalizer(() => Effect.gen(function* () {
        closing++;
        if (controls.closeGate) yield* Effect.promise(() => controls.closeGate!);
        transport.closed = true;
        closing--;
        transport.end();
      }));
      const meta = { backend: "codex" as const, nativeSessionId: transport.id };
      if (!checkpoint) transport.emit({ _tag: "UserMessage", text: task.prompt });
      transport.emit({ _tag: "MetaChanged", meta });
      return {
        meta: Effect.succeed(meta),
        events: Stream.fromQueue(events),
        checkpoint: () => !transport.active && transport.persistent
          ? { nativeSessionId: transport.id } : undefined,
        send: (text) => Effect.gen(function* () {
          if (controls.sendGate) yield* Effect.promise(() => controls.sendGate!);
          if (controls.failSend) return yield* new SendError({ message: "send failed" });
          assert.equal(transport.closed, false, "must never send to a closed transport");
          transport.sent.push(text);
          transport.active = true;
          transport.emit({ _tag: "RunStarted" });
          transport.emit({ _tag: "UserMessage", text });
        }),
        interrupt: Effect.sync(() => {
          transport.active = false;
          transport.emit({ _tag: "RunSettled", outcome: { _tag: "Interrupted" } });
        }),
      };
    });
  const backend: SubagentBackend = {
    name: "codex", available: Effect.succeed(true),
    capabilities: { steering: false, modelSelection: true, reasoningEffort: true },
    spawn: () => make(), resume: (_task, checkpoint) => make(checkpoint),
  };
  const runtime = ManagedRuntime.make(SubagentManagerLive.pipe(Layer.provide(
    Layer.succeed(BackendRegistry, new Map([["codex", backend]])),
  )));
  const manager = await runtime.runPromise(SubagentManager);
  const run = <A, E>(effect: Effect.Effect<A, E>) => runtime.runPromise(effect);
  const spawn = async () => {
    const snap = await run(manager.spawn("codex", task));
    return { snap, transport: transports.at(-1)! };
  };
  const finishOne = async () => {
    const result = await spawn();
    result.transport.finish();
    await run(manager.waitFor([result.snap.id]));
    await tick();
    return result;
  };
  return { manager, runtime, run, spawn, finishOne, transports, resumed, controls,
    get opening() { return opening; }, get closing() { return closing; } };
}

test("streaming reaches takeover only; footer and wait progress follow lifecycle/membership", async () => {
  const h = await harness();
  try {
    const { snap, transport } = await h.spawn();
    let global = 0;
    let local = 0;
    const pending: string[][] = [];
    h.manager.view.subscribe(() => { global++; });
    h.manager.view.subscribeTo(snap.id, () => { local++; });
    const waited = h.run(h.manager.waitFor([snap.id], (ids) => pending.push(ids)));
    await tick();
    const beforeGlobal = global;
    const beforeLocal = local;
    for (let n = 0; n < 200; n++) {
      transport.emit({ _tag: "AssistantDelta", kind: n % 2 ? "text" : "thinking", delta: "." });
      transport.emit({ _tag: "ToolUpdate", toolId: "tool", outputPreview: `${n}` });
      transport.emit({ _tag: "UsageChanged", tokens: n });
    }
    await tick();
    assert.equal(global, beforeGlobal);
    assert.equal(local - beforeLocal, 600);
    assert.deepEqual(pending, [[snap.id]]);
    const other = await h.spawn(); // global notification, unchanged wait membership
    await tick();
    assert.deepEqual(pending, [[snap.id]]);
    transport.finish();
    await waited;
    assert.equal(snap.status, "done");
    assert.ok(global > beforeGlobal);
    await h.run(h.manager.cancel([other.snap.id]));
    await h.run(h.manager.send(snap.id, "continue"));
    assert.equal(snap.status, "running");
  } finally { await h.runtime.dispose(); }
});

test("LRU retains two idle transports and all 64 results; dormant send resumes native history once", async () => {
  const h = await harness();
  try {
    const first = await h.finishOne();
    const second = await h.finishOne();
    h.manager.view.subscribeTo(first.snap.id, () => {})(); // viewing refreshes LRU
    await h.finishOne();
    assert.equal(first.transport.closed, false);
    assert.equal(second.transport.closed, true);
    for (let i = 3; i < MAX_TRACKED; i++) await h.finishOne();
    assert.equal(h.manager.view.size(), MAX_TRACKED);
    assert.equal(h.transports.filter((t) => !t.closed).length, MAX_IDLE_BACKENDS);
    assert.ok(h.manager.view.list().every((snap) => snap.status === "done" && snap.finalText === "answer"));
    const history = [...second.snap.transcript];
    const barrier = gate();
    h.controls.resumeGate = barrier.promise;
    const one = h.run(h.manager.send(second.snap.id, "next"));
    const two = h.run(h.manager.send(second.snap.id, "queued"));
    await tick();
    assert.equal(h.resumed.length, 1);
    assert.equal(second.snap.status, "running");
    let waited = false;
    const wait = h.run(h.manager.waitFor([second.snap.id])).then(() => { waited = true; });
    await tick();
    assert.equal(waited, false);
    barrier.resolve();
    await Promise.all([one, two]);
    const live = h.transports.at(-1)!;
    assert.equal(live.id, second.transport.id);
    assert.deepEqual(live.sent, ["next", "queued"]);
    await tick();
    assert.deepEqual(second.snap.transcript.slice(0, history.length), history);
    assert.equal(second.snap.transcript.filter((item) => item.kind === "user" && item.text === "initial").length, 1);
    live.finish("continued");
    await wait;
    await tick();
    assert.equal(second.snap.finalText, "continued");
    assert.equal(h.transports.filter((t) => !t.closed).length, MAX_IDLE_BACKENDS);
    await h.finishOne();
    assert.equal(h.manager.view.size(), MAX_TRACKED);
  } finally { await h.runtime.dispose(); }
});

test("resume waits for actual eviction teardown before opening another owner", async () => {
  const h = await harness();
  const barrier = gate();
  try {
    const first = await h.finishOne();
    await h.finishOne();
    h.controls.closeGate = barrier.promise;
    await h.finishOne();
    assert.equal(h.closing, 1);
    const sent = h.run(h.manager.send(first.snap.id, "next"));
    await tick();
    assert.equal(h.resumed.length, 0);
    barrier.resolve();
    await sent;
    assert.equal(first.transport.closed, true);
    assert.equal(h.resumed.length, 1);
  } finally { barrier.resolve(); await h.runtime.dispose(); }
});

test("opening sessions reserve capacity; cancel interrupts resume and rejects queued sends", async () => {
  const h = await harness();
  try {
    const first = await h.finishOne();
    await h.finishOne();
    await h.finishOne();
    const barrier = gate();
    h.controls.resumeGate = barrier.promise;
    const one = h.run(h.manager.send(first.snap.id, "cancel me")).catch((e: unknown) => e);
    const two = h.run(h.manager.send(first.snap.id, "cancel queued")).catch((e: unknown) => e);
    await tick();
    const running = await Promise.all([h.spawn(), h.spawn(), h.spawn()]);
    await assert.rejects(h.spawn(), /Max 4/);
    const cancel = await h.run(h.manager.cancel([first.snap.id]));
    await Promise.all([one, two]);
    assert.equal(cancel[0].cancelled, true);
    assert.equal(first.snap.status, "error");
    assert.equal(first.snap.errorText, "Run was aborted");
    assert.equal(h.opening, 0);
    barrier.resolve();
    h.controls.resumeGate = undefined;
    await h.run(h.manager.cancel(running.map(({ snap }) => snap.id)));
    await h.run(h.manager.send(first.snap.id, "retry after cancel"));
    assert.deepEqual(h.transports.at(-1)?.sent, ["retry after cancel"]);
  } finally { await h.runtime.dispose(); }
});

test("failed resume releases capacity and remains retryable without losing the transcript", async () => {
  const h = await harness();
  try {
    const first = await h.finishOne();
    await h.finishOne();
    await h.finishOne();
    const history = [...first.snap.transcript];
    h.controls.failResume = true;
    await assert.rejects(h.run(h.manager.send(first.snap.id, "fail")), /resume failed/);
    assert.equal(first.snap.status, "error");
    assert.match(first.snap.errorText ?? "", /resume failed/);
    assert.deepEqual(first.snap.transcript, history);
    assert.equal(h.opening, 0);
    h.controls.failResume = false;
    await h.run(h.manager.send(first.snap.id, "retry"));
    assert.equal(first.snap.status, "running");
    h.transports.at(-1)!.finish("retry result");
    await h.run(h.manager.waitFor([first.snap.id]));
    assert.equal(first.snap.finalText, "retry result");
  } finally { await h.runtime.dispose(); }
});

test("a queued send rechecks status after the preceding send failed", async () => {
  const h = await harness();
  try {
    const first = await h.finishOne();
    const barrier = gate();
    h.controls.sendGate = barrier.promise;
    h.controls.failSend = true;
    const failure = h.run(h.manager.send(first.snap.id, "fail")).catch((e: unknown) => e);
    await tick();
    const queued = h.run(h.manager.send(first.snap.id, "retry"));
    // The first failure hook changes the boundary before the next permit holder.
    h.manager.view.setOnSettled(() => { h.controls.failSend = false; });
    barrier.resolve();
    await failure;
    await queued;
    assert.equal(first.snap.status, "running");
    first.transport.finish();
    await h.run(h.manager.waitFor([first.snap.id]));
  } finally { await h.runtime.dispose(); }
});

test("idle stream death closes below the LRU cap and resumes; active death settles once", async () => {
  const h = await harness();
  try {
    const first = await h.finishOne();
    first.transport.end();
    await tick();
    await tick();
    assert.equal(first.transport.closed, true);
    assert.equal(first.snap.status, "done");
    await h.run(h.manager.send(first.snap.id, "after idle death"));
    let settles = 0;
    h.manager.view.setOnSettled(() => { settles++; });
    h.transports.at(-1)!.end();
    await h.run(h.manager.waitFor([first.snap.id]));
    await tick();
    assert.equal(first.snap.status, "error");
    assert.match(first.snap.errorText ?? "", /stream ended/);
    assert.equal(settles, 1);
    await h.run(h.manager.send(first.snap.id, "after active death"));
    assert.equal(first.snap.status, "running");
  } finally { await h.runtime.dispose(); }
});

test("missing persistence pins the only history instead of silently starting blank", async () => {
  const h = await harness();
  try {
    const first = await h.spawn();
    first.transport.persistent = false;
    first.transport.finish();
    await h.run(h.manager.waitFor([first.snap.id]));
    await h.finishOne();
    await h.finishOne();
    assert.equal(first.transport.closed, false);
    await h.run(h.manager.send(first.snap.id, "same in-memory history"));
    assert.deepEqual(first.transport.sent, ["same in-memory history"]);
    assert.equal(h.resumed.length, 0);
  } finally { await h.runtime.dispose(); }
});

test("dispose during resume closes acquisition and never resurrects a tracked entry", async () => {
  const h = await harness();
  try {
    const first = await h.finishOne();
    await h.finishOne();
    await h.finishOne();
    const barrier = gate();
    h.controls.resumeGate = barrier.promise;
    const send = h.run(h.manager.send(first.snap.id, "never dispatch")).catch((e: unknown) => e);
    await tick();
    await h.run(h.manager.disposeAll);
    barrier.resolve();
    await send;
    await tick();
    assert.equal(h.opening, 0);
    assert.equal(h.manager.view.size(), 0);
    assert.ok(h.transports.every((t) => t.closed));
    await assert.rejects(h.run(h.manager.send(first.snap.id, "late")), /no longer tracked/);
  } finally { await h.runtime.dispose(); }
});

test("cached multi-part messages do not overflow the argument stack", async () => {
  const h = await harness();
  try {
    const { snap, transport } = await h.spawn();
    transport.emit({ _tag: "AssistantMessage", parts: Array.from({ length: 80 }, () => ({ type: "text", text: "x\n".repeat(2_000) })) });
    transport.finish();
    await h.run(h.manager.waitFor([snap.id]));
    const theme = { fg: (_color: string, text: string) => text, italic: (text: string) => text } as Theme;
    const cache = new CompletedTranscriptCache();
    const first = buildTranscriptLines(snap, 80, theme, cache);
    assert.ok(first.length > 150_000);
    assert.deepEqual(buildTranscriptLines(snap, 80, theme, cache), first);
  } finally { await h.runtime.dispose(); }
});

test("completed transcript rendering is cached until width or theme invalidation", async () => {
  const h = await harness();
  try {
    const { snap, transport } = await h.spawn();
    transport.finish("cached answer");
    await h.run(h.manager.waitFor([snap.id]));
    let styles = 0;
    const theme = {
      fg: (_color: string, text: string) => { styles++; return text; },
      italic: (text: string) => text,
    } as Theme;
    const cache = new CompletedTranscriptCache();

    const first = buildTranscriptLines(snap, 80, theme, cache);
    const firstStyles = styles;
    assert.ok(firstStyles > 0);
    assert.deepEqual(buildTranscriptLines(snap, 80, theme, cache), first);
    assert.equal(styles, firstStyles);

    buildTranscriptLines(snap, 40, theme, cache);
    assert.ok(styles > firstStyles);
    const resizedStyles = styles;
    cache.invalidate();
    buildTranscriptLines(snap, 40, theme, cache);
    assert.ok(styles > resizedStyles);
  } finally { await h.runtime.dispose(); }
});
