import assert from "node:assert/strict";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import test from "node:test";
import type { SubagentSession } from "./src/backend.ts";
import type { SpawnTask } from "./src/domain.ts";

const task: SpawnTask = {
  title: "native resume test",
  prompt: "must not replay",
  cwd: process.cwd(),
  parent: { parentCwd: process.cwd(), projectTrusted: false },
};

async function waitForLog(path: string, predicate: (lines: unknown[]) => boolean) {
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    const text = await readFile(path, "utf8").catch(() => "");
    const lines = text.trim() ? text.trim().split("\n").map((line) => JSON.parse(line)) : [];
    if (predicate(lines)) return lines;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("Timed out waiting for fake Codex protocol log");
}

test("Codex resume uses thread/resume and continues the native thread without replaying the initial prompt", async () => {
  const dir = await mkdtemp(join(tmpdir(), "subagents-codex-resume-"));
  const log = join(dir, "protocol.jsonl");
  const executable = join(dir, "codex");
  await writeFile(executable, `#!/usr/bin/env node
const fs = require("node:fs");
const readline = require("node:readline");
const log = process.env.CODEX_TEST_LOG;
const append = (value) => fs.appendFileSync(log, JSON.stringify(value) + "\\n");
readline.createInterface({ input: process.stdin }).on("line", (line) => {
  const message = JSON.parse(line); append(message);
  if (message.id === undefined) return;
  if (message.method === "initialize") console.log(JSON.stringify({ id: message.id, result: {} }));
  else if (message.method === "thread/resume") console.log(JSON.stringify({ id: message.id, result: { thread: { id: message.params.threadId, path: "/saved/rollout.jsonl" }, model: "gpt-test" } }));
  else if (message.method === "turn/start") console.log(JSON.stringify({ id: message.id, result: { turn: { id: "turn-1" } } }));
  else console.log(JSON.stringify({ id: message.id, result: {} }));
});
`, "utf8");
  await chmod(executable, 0o755);

  const previousPath = process.env.PATH;
  const previousLog = process.env.CODEX_TEST_LOG;
  process.env.PATH = `${dir}${delimiter}${previousPath ?? ""}`;
  process.env.CODEX_TEST_LOG = log;
  try {
    const { Effect, Exit, Scope } = await import("effect");
    const { codexBackend } = await import("./src/backends/codex.ts");
    const scope = await Effect.runPromise(Scope.make());
    try {
      const session = await Effect.runPromise(Scope.provide(
        codexBackend.resume!(task, { nativeSessionId: "thread-existing" }),
        scope,
      )) as SubagentSession;
      const beforeSend = await waitForLog(log, (lines) => lines.some((line: any) => line.method === "thread/resume"));
      const resume = beforeSend.find((line: any) => line.method === "thread/resume") as any;
      assert.equal(resume.params.threadId, "thread-existing");
      assert.equal(beforeSend.some((line: any) => line.method === "thread/start"), false);
      assert.equal(beforeSend.some((line: any) => JSON.stringify(line).includes(task.prompt)), false);
      assert.equal((await Effect.runPromise(session.meta)).nativeSessionId, "thread-existing");

      await Effect.runPromise(session.send("continue native history"));
      const afterSend = await waitForLog(log, (lines) => lines.some((line: any) =>
        line.method === "turn/start" && JSON.stringify(line).includes("continue native history")));
      const turn = afterSend.find((line: any) => line.method === "turn/start") as any;
      assert.equal(turn.params.threadId, "thread-existing");
    } finally {
      await Effect.runPromise(Scope.close(scope, Exit.void));
    }
  } finally {
    if (previousPath === undefined) delete process.env.PATH;
    else process.env.PATH = previousPath;
    if (previousLog === undefined) delete process.env.CODEX_TEST_LOG;
    else process.env.CODEX_TEST_LOG = previousLog;
    await rm(dir, { recursive: true, force: true });
  }
});
