import assert from "node:assert/strict";
import { EventEmitter, once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";
import test from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type Handler = (event: unknown, ctx: { mode: string }) => void | Promise<void>;

function metadata(line: string) {
  const value: unknown = JSON.parse(line);
  assert.ok(value !== null && typeof value === "object");
  assert.ok("id" in value && typeof value.id === "string" && value.id.length > 0);
  assert.ok("method" in value);
  assert.equal(value.method, "pane.report_metadata");
  assert.ok("params" in value && value.params !== null && typeof value.params === "object");
  const params = value.params;
  assert.ok("source" in params);
  assert.equal(params.source, "herdr:pi-session-name");
  assert.ok("pane_id" in params);
  assert.equal(params.pane_id, "test-pane");
  assert.ok("seq" in params && typeof params.seq === "number");
  assert.ok(Number.isSafeInteger(params.seq));
  assert.ok("tokens" in params && params.tokens !== null && typeof params.tokens === "object");
  assert.ok("pi_session" in params.tokens);
  const name = params.tokens.pi_session;
  assert.ok(name === null || typeof name === "string");
  return { seq: params.seq, name };
}

test("reports session metadata only for the owning TUI session", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "herdr-name-test-"));
  const socketPath = join(directory, "socket");
  const original = new Map<string, string | undefined>();
  const environment = { HERDR_ENV: "1", HERDR_SOCKET_PATH: socketPath, HERDR_PANE_ID: "test-pane" };
  for (const [key, value] of Object.entries(environment)) {
    original.set(key, process.env[key]);
    process.env[key] = value;
  }
  const sockets = new Set<net.Socket>();
  const events = new EventEmitter();
  const lines: string[] = [];
  const server = net.createServer((socket) => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
    createInterface({ input: socket }).on("line", (line) => {
      lines.push(line);
      socket.once("close", () => events.emit("request", line));
      socket.write("{}\n");
    });
  });
  t.after(async () => {
    for (const socket of sockets) socket.destroy();
    if (server.listening) await new Promise<void>((resolve) => server.close(() => resolve()));
    for (const [key, value] of original) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(directory, { recursive: true, force: true });
  });
  const listening = once(server, "listening");
  server.listen(socketPath);
  await listening;
  // The extension captures its socket configuration on import.
  const { default: install } = await import("../herdr-pi-session-name.ts");

  function setup() {
    const handlers = new Map<string, Handler>();
    const pi = {
      on(event: string, handler: Handler) { handlers.set(event, handler); },
      getSessionName: () => "initial name",
    };
    // Only the event and name surfaces used by this extension are stubbed.
    install(pi as unknown as ExtensionAPI);
    return async (event: string, data: unknown, mode = "tui") => {
      const handler = handlers.get(event);
      assert.ok(handler, `missing handler: ${event}`);
      await handler(data, { mode });
    };
  }

  async function request(action: () => Promise<void>) {
    const pending = once(events, "request", { signal: AbortSignal.timeout(2000) });
    await action();
    const [line]: unknown[] = await pending;
    assert.ok(typeof line === "string");
    return metadata(line);
  }

  await t.test("ignores metadata events before startup and in all headless modes", async () => {
    for (const mode of ["rpc", "json", "print"]) {
      const emit = setup();
      await emit("session_info_changed", { name: "before start" }, mode);
      await emit("session_start", { reason: "startup" }, mode);
      await emit("session_info_changed", { name: "headless rename" }, mode);
    }
    assert.deepEqual(lines, []);
  });

  const emit = setup();
  let previousSeq = 0;
  await t.test("sends the initial name with the expected source and pane", async () => {
    const first = await request(() => emit("session_start", { reason: "startup" }));
    assert.equal(first.name, "initial name");
    assert.ok(first.seq > previousSeq);
    previousSeq = first.seq;
    assert.equal(lines.length, 1);
  });

  await t.test("reports rename with an increasing sequence", async () => {
    const renamed = await request(() => emit("session_info_changed", { name: "renamed" }));
    assert.equal(renamed.name, "renamed");
    assert.ok(renamed.seq > previousSeq);
    previousSeq = renamed.seq;
  });

  await t.test("clears a name with null and keeps the sequence increasing", async () => {
    const cleared = await request(() => emit("session_info_changed", { name: undefined }));
    assert.equal(cleared.name, null);
    assert.ok(cleared.seq > previousSeq);
    assert.equal(lines.length, 3);
  });
});
