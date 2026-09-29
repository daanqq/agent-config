import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate } from "node:timers/promises";
import autoSessionNameExtension, { sanitizeSessionName } from "./index.ts";

type Handler = (event: any, ctx: any) => unknown;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function createHarness() {
  const handlers = new Map<string, Handler>();
  const commands = new Map<string, (args: string, ctx: any) => Promise<void>>();
  const notifications: Array<{ message: string; type: string }> = [];
  const completion = deferred<any>();
  const queuedCompletions: Array<Promise<any>> = [];
  let completionRequest: any;
  let completionCalls = 0;
  let name: string | undefined;
  let sessionId = "session-1";
  let sessionFile: string | undefined = "/tmp/session-1.jsonl";
  let branch: any[] = [];

  const pi = {
    on(event: string, handler: Handler) {
      handlers.set(event, handler);
    },
    registerCommand(name: string, options: { handler: (args: string, ctx: any) => Promise<void> }) {
      commands.set(name, options.handler);
    },
    setSessionName(nextName: string) {
      name = nextName;
    },
  };

  const ctx = {
    mode: "tui",
    waitForIdle: async () => {},
    ui: {
      notify(message: string, type: string) {
        notifications.push({ message, type });
      },
    },
    sessionManager: {
      getBranch: () => branch,
      getSessionId: () => sessionId,
      getSessionFile: () => sessionFile,
      getSessionName: () => name,
    },
    modelRegistry: {
      find: (provider: string, id: string) => {
        assert.equal(provider, "openai-codex");
        assert.equal(id, "gpt-5.6-luna");
        return { provider, id };
      },
      complete: (...args: any[]) => {
        completionCalls += 1;
        completionRequest = args;
        return queuedCompletions.shift() ?? completion.promise;
      },
    },
  };

  autoSessionNameExtension(pi as any);

  const emit = (event: string, payload: Record<string, unknown> = {}) => handlers.get(event)?.({ type: event, ...payload }, ctx);

  return {
    ctx,
    notifications,
    completion,
    queueCompletion(promise: Promise<any>) {
      queuedCompletions.push(promise);
    },
    emit,
    runCommand(name: string, args = "") {
      return commands.get(name)?.(args, ctx) ?? Promise.reject(new Error(`Unknown command: ${name}`));
    },
    getCompletionCalls: () => completionCalls,
    getCompletionRequest: () => completionRequest,
    getName: () => name,
    setName(nextName: string | undefined) {
      name = nextName;
    },
    emitNameChange(nextName: string | undefined) {
      name = nextName;
      emit("session_info_changed", { name: nextName });
    },
    setSession(nextId: string, nextFile: string) {
      sessionId = nextId;
      sessionFile = nextFile;
    },
    setBranch(nextBranch: any[]) {
      branch = nextBranch;
    },
  };
}

async function startNaming(harness: ReturnType<typeof createHarness>) {
  harness.emit("session_start", { reason: "startup" });
  harness.emit("before_agent_start", { prompt: "Исправь обновление токена авторизации" });
  harness.emit("agent_end", {
    messages: [{ role: "assistant", content: [{ type: "text", text: "Нашёл гонку и исправил обновление токена." }] }],
  });
  harness.emit("agent_settled");
  await Promise.resolve();
}

test("sanitizes and limits generated names", () => {
  assert.equal(sanitizeSessionName('## "Исправление обновления токена."'), "Исправление обновления токена");
  assert.equal(sanitizeSessionName("Title: Короткое название\nЛишняя строка"), "Короткое название");
  assert.equal(sanitizeSessionName("```text\nИмя в блоке кода\n```"), "Имя в блоке кода");
  assert.equal(sanitizeSessionName("Разбор авторизации。"), "Разбор авторизации");
  assert.ok(sanitizeSessionName("Очень длинное название ".repeat(10)).length <= 60);
});

test("requests an English name for a Russian conversation once after the first settled response", async () => {
  const harness = createHarness();
  await startNaming(harness);

  assert.deepEqual(harness.notifications, [{ message: "Generating session name...", type: "info" }]);

  harness.completion.resolve({ content: [{ type: "text", text: "Authentication token refresh" }] });
  await setImmediate();

  assert.equal(harness.getName(), "gen: Authentication token refresh");
  assert.equal(harness.getCompletionCalls(), 1);
  const [model, context, options] = harness.getCompletionRequest();
  assert.deepEqual(model, { provider: "openai-codex", id: "gpt-5.6-luna" });
  assert.match(context.systemPrompt, /Always use English, regardless of the language of the user's request/);
  assert.doesNotMatch(context.systemPrompt, /Use the same language/);
  assert.match(context.messages[0].content[0].text, /Исправь обновление токена авторизации/);
  assert.match(context.messages[0].content[0].text, /Нашёл гонку и исправил обновление токена/);
  assert.equal(options.reasoningEffort, "low");
  assert.equal(options.maxTokens, 80);
  assert.equal(options.cacheRetention, "none");
  assert.equal(options.timeoutMs, 15_000);
  assert.equal(options.maxRetries, 0);
  assert.ok(options.signal instanceof AbortSignal);
  assert.deepEqual(harness.notifications, [
    { message: "Generating session name...", type: "info" },
    { message: "Session name: gen: Authentication token refresh", type: "info" },
  ]);

  harness.emit("agent_settled");
  assert.equal(harness.getCompletionCalls(), 1);
});

test("uses an English fallback for a Russian request when generation fails", async () => {
  const harness = createHarness();
  await startNaming(harness);

  harness.completion.reject(new Error("provider unavailable"));
  await setImmediate();

  assert.equal(harness.getName(), "gen: New session");
  assert.deepEqual(harness.notifications, [
    { message: "Generating session name...", type: "info" },
    { message: "Session naming failed; using fallback.", type: "warning" },
    { message: "Session name: gen: New session", type: "info" },
  ]);
});

test("regenerates a fallback name with /namegen", async () => {
  const harness = createHarness();
  await startNaming(harness);

  harness.completion.reject(new Error("provider unavailable"));
  await setImmediate();
  assert.equal(harness.getName(), "gen: New session");

  const retry = deferred<any>();
  harness.queueCompletion(retry.promise);
  const command = harness.runCommand("namegen");
  await setImmediate();

  assert.equal(harness.getCompletionCalls(), 2);
  assert.match(harness.getCompletionRequest()[1].messages[0].content[0].text, /Исправь обновление токена авторизации/);
  retry.resolve({ content: [{ type: "text", text: "Authentication Token Refresh" }] });
  await command;

  assert.equal(harness.getName(), "gen: Authentication Token Refresh");
  assert.deepEqual(harness.notifications.slice(-2), [
    { message: "Generating session name...", type: "info" },
    { message: "Session name: gen: Authentication Token Refresh", type: "info" },
  ]);
});

test("preserves a manual name set while generation is pending", async () => {
  const harness = createHarness();
  await startNaming(harness);

  harness.setName("Ручное имя");
  harness.completion.resolve({ content: [{ type: "text", text: "Автоматическое имя" }] });
  await setImmediate();

  assert.equal(harness.getName(), "Ручное имя");
  assert.deepEqual(harness.notifications, [{ message: "Generating session name...", type: "info" }]);
});

test("does not show a fallback warning after a manual rename", async () => {
  const harness = createHarness();
  await startNaming(harness);

  harness.setName("Ручное имя");
  harness.completion.reject(new Error("provider unavailable"));
  await setImmediate();

  assert.equal(harness.getName(), "Ручное имя");
  assert.deepEqual(harness.notifications, [{ message: "Generating session name...", type: "info" }]);
});

test("does not restore an automatic name after the user clears a manual name", async () => {
  const harness = createHarness();
  await startNaming(harness);

  harness.emitNameChange("Ручное имя");
  harness.emitNameChange(undefined);
  harness.completion.resolve({ content: [{ type: "text", text: "Автоматическое имя" }] });
  await setImmediate();

  assert.equal(harness.getName(), undefined);
  assert.deepEqual(harness.notifications, [{ message: "Generating session name...", type: "info" }]);
});

test("does not write a generated name after the session changes", async () => {
  const harness = createHarness();
  await startNaming(harness);

  harness.setSession("session-2", "/tmp/session-2.jsonl");
  harness.completion.resolve({ content: [{ type: "text", text: "Устаревшее имя" }] });
  await setImmediate();

  assert.equal(harness.getName(), undefined);
  assert.deepEqual(harness.notifications, [{ message: "Generating session name...", type: "info" }]);
});

for (const reason of ["quit", "reload", "new", "resume", "fork"]) {
  test(`cancels naming without waiting on provider during ${reason}`, async () => {
    const harness = createHarness();
    await startNaming(harness);
    const signal: AbortSignal = harness.getCompletionRequest()[2].signal;
    assert.equal(signal.aborted, false);

    // The provider deliberately ignores abort and stays pending.
    assert.equal(harness.emit("session_shutdown", { reason }), undefined);
    assert.equal(signal.aborted, true);
    harness.completion.resolve({ content: [{ type: "text", text: "Late name" }] });
    await setImmediate();
    assert.equal(harness.getName(), undefined);
    assert.deepEqual(harness.notifications, [{ message: "Generating session name...", type: "info" }]);
  });
}

test("a naming deadline still uses fallback while the session stays open", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const harness = createHarness();
  await startNaming(harness);
  const signal: AbortSignal = harness.getCompletionRequest()[2].signal;
  signal.addEventListener("abort", () => harness.completion.reject(new Error("timeout")), { once: true });
  t.mock.timers.tick(15_000);
  await setImmediate();
  assert.equal(harness.getName(), "gen: New session");
  assert.equal(harness.notifications.length, 3);
});

test("a cancelled request cannot name a replacement session", async () => {
  const harness = createHarness();
  await startNaming(harness);
  harness.emit("session_shutdown", { reason: "new" });
  harness.emit("session_start", { reason: "new" });
  harness.completion.reject(new Error("aborted"));
  await setImmediate();
  assert.equal(harness.getName(), undefined);
  assert.deepEqual(harness.notifications, [{ message: "Generating session name...", type: "info" }]);
});

test("ignores resumed sessions and sessions with message history", () => {
  const resumed = createHarness();
  resumed.emit("session_start", { reason: "resume" });
  resumed.emit("before_agent_start", { prompt: "Новый запрос" });
  resumed.emit("agent_end", { messages: [{ role: "assistant", content: "Ответ" }] });
  resumed.emit("agent_settled");
  assert.equal(resumed.getCompletionCalls(), 0);

  const existing = createHarness();
  existing.setBranch([{ type: "message", message: { role: "user", content: "Старый запрос" } }]);
  existing.emit("session_start", { reason: "startup" });
  existing.emit("before_agent_start", { prompt: "Новый запрос" });
  existing.emit("agent_end", { messages: [{ role: "assistant", content: "Ответ" }] });
  existing.emit("agent_settled");
  assert.equal(existing.getCompletionCalls(), 0);

  const emptyPersisted = createHarness();
  emptyPersisted.setSession("session-existing", "/etc/hosts");
  emptyPersisted.emit("session_start", { reason: "startup" });
  emptyPersisted.emit("before_agent_start", { prompt: "Новый запрос" });
  emptyPersisted.emit("agent_end", { messages: [{ role: "assistant", content: "Ответ" }] });
  emptyPersisted.emit("agent_settled");
  assert.equal(emptyPersisted.getCompletionCalls(), 0);
});
