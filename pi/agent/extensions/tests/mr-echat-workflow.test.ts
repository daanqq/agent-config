import assert from "node:assert/strict";
import test from "node:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionCommandContext, Theme, KeybindingsManager } from "@earendil-works/pi-coding-agent";
import { ProcessTerminal, TuiMainScreen, stripTerminalSequences } from "@earendil-works/pi-tui";
import mrEchat from "../mr-echat.ts";
import type { MrEchatPanel } from "../shared/mr-echat-panel.ts";

type Command = Parameters<ExtensionAPI["registerCommand"]>[1];

async function until(predicate: () => boolean) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
  assert.fail("Workflow did not reach the expected UI state");
}

function setup({ commitFails = false, holdPush = false, noLocalDiff = false, branch = "feature/T-183060", existingMr = true, targetBranch = "master", repoDir = "/tmp/echat", previousTitle = "fix request title button #T-183060", gitReplies = {} as Record<string, { stdout: string; code: number }> } = {}) {
  let command: Command | undefined;
  let panel: MrEchatPanel | undefined;
  let opens = 0;
  let closes = 0;
  let releasePush: (() => void) | undefined;
  const calls: string[] = [];
  const nativeUI: string[] = [];
  const snapshots: string[][] = [];
  const generationSignals: AbortSignal[] = [];
  const handlers = new Map<string, () => void>();
  const plain = (text: string) => text;
  const theme = { fg: (_color: string, text: string) => text, bold: plain } as unknown as Theme;
  const keybindings = { matches: () => false, getKeys: () => [] } as unknown as KeybindingsManager;
  const tui = new TuiMainScreen(new ProcessTerminal());
  tui.requestRender = () => {
    if (panel) snapshots.push(panel.render(80).map(stripTerminalSequences));
  };
  const pi = {
    on(name: string, handler: () => void) { handlers.set(name, handler); },
    registerCommand(_name: string, value: Command) { command = value; },
    async exec(cmd: string, args: string[]) {
      const invocation = `${cmd} ${args.join(" ")}`;
      calls.push(invocation);
      const reply = gitReplies[invocation];
      if (reply) return { ...reply, stderr: "", killed: false };
      if (args[0] === "push" && holdPush) {
        await new Promise<void>((resolve) => { releasePush = resolve; });
      }
      let stdout = "";
      if (args.join(" ") === "rev-parse --show-toplevel") stdout = repoDir;
      else if (args.join(" ") === "branch --show-current") stdout = branch;
      else if (cmd === "glab" && args[1] === "list") {
        stdout = existingMr
          ? JSON.stringify([{ iid: 1, web_url: "https://gitlab.example/echat/-/merge_requests/1", target_branch: targetBranch }])
          : "[]";
      } else if (cmd === "glab" && args[1] === "view") stdout = "Existing description";
      else if (args[0] === "log") stdout = previousTitle;
      else if (args[0] === "diff") {
        stdout = noLocalDiff && !args.some((arg) => arg.includes("...HEAD"))
          ? "" : args.includes("--name-only") ? "file.ts" : "+changed";
      }
      const code = args[0] === "commit" && commitFails ? 1 : 0;
      return { stdout, stderr: code ? "hook failed" : "", code, killed: false };
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    mode: "tui", cwd: "/tmp/echat", waitForIdle: async () => {},
    sessionManager: { getBranch: () => [], getSessionId: () => "test" },
    getSystemPrompt: () => "System prompt",
    modelRegistry: {
      find: () => ({ provider: "test", id: "test" }),
      getApiKeyAndHeaders: async () => ({ ok: true, apiKey: "test-only-not-a-credential" }),
      streamSimple(_model: unknown, _context: unknown, options: { signal: AbortSignal }) {
        generationSignals.push(options.signal);
        return {
          result: () => new Promise((resolve) => {
            const aborted = () => resolve({ role: "assistant", content: [], stopReason: "aborted" });
            if (options.signal.aborted) aborted();
            else options.signal.addEventListener("abort", aborted, { once: true });
          }),
        };
      },
    },
    ui: {
      notify(message: string) { nativeUI.push(message); },
      select: async () => { nativeUI.push("select"); return undefined; },
      input: async () => { nativeUI.push("input"); return undefined; },
      confirm: async () => { nativeUI.push("confirm"); return false; },
      setWidget: () => nativeUI.push("widget"),
      custom(factory: (tui: TuiMainScreen, theme: Theme, kb: KeybindingsManager, done: () => void) => MrEchatPanel) {
        opens++;
        return new Promise<void>((resolve) => {
          panel = factory(tui, theme, keybindings, () => {
            closes++;
            panel?.dispose();
            resolve();
          });
          panel.focused = true;
          tui.requestRender();
        });
      },
    },
  } as unknown as ExtensionCommandContext;
  mrEchat(pi);
  return {
    calls, nativeUI, snapshots, generationSignals,
    get opens() { return opens; }, get closes() { return closes; },
    get panel() { return panel!; },
    view: () => panel?.render(80).map(stripTerminalSequences).join("\n") ?? "",
    start: (args = "") => command!.handler(args, ctx),
    shutdown: () => handlers.get("session_shutdown")?.(),
    releasePush: () => releasePush?.(),
  };
}

async function choosePrevious(fixture: ReturnType<typeof setup>) {
  await until(() => fixture.view().includes("Использовать существующее"));
  fixture.panel.handleInput("\r");
  await until(() => fixture.view().includes("Дополнить описание MR"));
}

test("one fixed-height panel owns selection, push and final result without widgets or editor transitions", async () => {
  const fixture = setup({ holdPush: true });
  const running = fixture.start();
  await choosePrevious(fixture);
  fixture.panel.handleInput("\x1b[B"); // Нет: do not call a model to update the description.
  fixture.panel.handleInput("\r");
  await until(() => fixture.calls.some((call) => call.startsWith("git push")));
  assert.match(fixture.view(), /Отправляю изменения/);
  fixture.panel.handleInput("\x1b"); // Running push cannot be cancelled from the panel.
  assert.equal(fixture.closes, 0);
  const duplicate = fixture.start();
  await duplicate;
  assert.equal(fixture.opens, 1);
  assert.match(fixture.nativeUI[0]!, /ещё выполняется/);
  fixture.nativeUI.length = 0;
  fixture.releasePush();
  await until(() => fixture.view().includes("MR уже существует:"));
  assert.equal(fixture.opens, 1);
  assert.equal(fixture.closes, 0); // Final URL remains visible until acknowledgement.
  fixture.panel.handleInput("\r");
  await running;
  assert.equal(fixture.closes, 1);
  assert.deepEqual(fixture.nativeUI, ["MR уже существует: https://gitlab.example/echat/-/merge_requests/1"]);
  assert.equal(new Set(fixture.snapshots.map((lines) => lines.length)).size, 1);
  assert.equal(fixture.calls.filter((call) => call.startsWith("git commit")).length, 1);
  assert.equal(fixture.calls.filter((call) => call.startsWith("git push")).length, 1);
});

test("Escape from the MR confirmation stops before commit rather than being treated as No", async () => {
  const fixture = setup();
  const running = fixture.start();
  await choosePrevious(fixture);
  fixture.panel.handleInput("\x1b");
  await until(() => fixture.view().includes("Команда mr-echat отменена"));
  assert.equal(fixture.calls.some((call) => call.startsWith("git commit") || call.startsWith("git push")), false);
  fixture.panel.handleInput("\r");
  await running;
  assert.equal(fixture.closes, 1);
});

test("commit failure stays inside the panel and prevents push", async () => {
  const fixture = setup({ commitFails: true });
  const running = fixture.start();
  await choosePrevious(fixture);
  fixture.panel.handleInput("\x1b[B");
  fixture.panel.handleInput("\r");
  await until(() => fixture.view().includes("hook failed"));
  assert.equal(fixture.calls.some((call) => call.startsWith("git push")), false);
  assert.equal(fixture.closes, 0);
  fixture.panel.handleInput("\r");
  await running;
  assert.deepEqual(fixture.nativeUI, ["Ошибка git commit: hook failed"]);
});

test("Escape aborts description generation without fallback, MR update or closing the panel early", async () => {
  const fixture = setup({ noLocalDiff: true });
  const running = fixture.start();
  await until(() => fixture.generationSignals.length === 1);
  assert.match(fixture.view(), /Обновляю описание/);
  fixture.panel.handleInput("\x1b");
  await until(() => fixture.view().includes("Генерация отменена"));
  assert.equal(fixture.generationSignals[0]!.aborted, true);
  assert.equal(fixture.generationSignals.length, 1);
  assert.equal(fixture.calls.some((call) => call.startsWith("glab mr update") || call.startsWith("git commit")), false);
  assert.equal(fixture.closes, 0);
  fixture.panel.handleInput("\r");
  await running;
  assert.equal(fixture.closes, 1);
});

test("branch IDs are matched exactly and legacy identifiers are rejected", async () => {
  const fixture = setup({ branch: "feature/J-183060" });
  const running = fixture.start();
  await until(() => fixture.view().includes("Ожидалось точное имя"));
  assert.equal(fixture.calls.some((call) => call.startsWith("git commit")), false);
  fixture.panel.handleInput("\r");
  await running;
});

test("task branch without an unambiguous feature parent stops before commit", async () => {
  const fixture = setup({ branch: "task/T-183061", existingMr: false });
  const running = fixture.start();
  await until(() => fixture.view().includes("однозначно определить"));
  assert.equal(fixture.calls.some((call) => call.startsWith("git commit")), false);
  assert.equal(fixture.calls.some((call) => call.startsWith("glab mr create")), false);
  fixture.panel.handleInput("\r");
  await running;
});

test("commit title gets its current T-ID exactly once without legacy suffix", async () => {
  const fixture = setup({ previousTitle: "fix rendering #T-183060 #EUTP-456" });
  const running = fixture.start();
  await choosePrevious(fixture);
  fixture.panel.handleInput("\x1b[B");
  fixture.panel.handleInput("\r");
  await until(() => fixture.view().includes("MR уже существует:"));
  assert.ok(fixture.calls.includes("git commit -m fix rendering #T-183060"));
  fixture.panel.handleInput("\r");
  await running;
});

test("requested invalid branch is rejected before switching", async () => {
  const fixture = setup({ branch: "master" });
  const running = fixture.start("--name=feature/J-123");
  await until(() => fixture.view().includes("Ожидалось точное имя"));
  assert.equal(fixture.calls.some((call) => call.startsWith("git switch")), false);
  fixture.panel.handleInput("\r");
  await running;
});

test("new task branch is never created from integration", async () => {
  for (const args of ["--name=task/T-124", "task/T-124"]) {
    const fixture = setup({ branch: "master", gitReplies: {
      "git show-ref --verify --quiet refs/heads/task/T-124": { stdout: "", code: 1 },
      "git show-ref --verify --quiet refs/remotes/origin/task/T-124": { stdout: "", code: 1 },
    } });
    const running = fixture.start(args);
    await until(() => fixture.view().includes("только от текущей родительской"));
    assert.equal(fixture.calls.some((call) => call.startsWith("git switch")), false);
    assert.equal(fixture.calls.some((call) => call.startsWith("git commit")), false);
    fixture.panel.handleInput("\r");
    await running;
  }
});

test("existing task MR to integration is blocked without changing its target", async () => {
  const fixture = setup({ branch: "task/T-124" });
  const running = fixture.start();
  await until(() => fixture.view().includes("MR задачи должен"));
  assert.equal(fixture.calls.some((call) => call.startsWith("glab mr update") || call.startsWith("git commit")), false);
  fixture.panel.handleInput("\r");
  await running;
});

test("new task starts from its feature parent and resolves only template placeholders", async () => {
  const repoDir = fs.mkdtempSync(path.join(os.tmpdir(), "spacehub-mr-template-"));
  try {
    const dir = path.join(repoDir, ".gitlab/merge_request_templates");
    fs.mkdirSync(dir, { recursive: true });
    const templatePath = path.join(dir, "Default.md");
    fs.writeFileSync(templatePath, "https://spacehub.esoft.tech/entity/T-…\nhttps://urs.esoft.tech/issue/EUTP-\nhttps://spacehub.esoft.tech/entity/T-999\n");
    const fixture = setup({ branch: "feature/T-123", existingMr: false, repoDir, gitReplies: {
      "git show-ref --verify --quiet refs/heads/task/T-124": { stdout: "", code: 1 },
      "git show-ref --verify --quiet refs/remotes/origin/task/T-124": { stdout: "", code: 1 },
    } });
    const running = fixture.start("task/T-124");
    await until(() => fixture.view().includes("Использовать существующее"));
    assert.ok(fixture.calls.includes("git switch -c task/T-124 feature/T-123"));
    assert.equal(fixture.calls.some((call) => call.includes("symbolic-ref")), false);
    fixture.panel.handleInput("\x1b");
    await until(() => fixture.view().includes("Команда mr-echat отменена"));
    fixture.panel.handleInput("\r");
    await running;

    fs.writeFileSync(templatePath, "https://spacehub.esoft.tech/entity/T-UNKNOWN\n");
    const invalid = setup({ existingMr: false, repoDir });
    const invalidRun = invalid.start();
    await until(() => invalid.view().includes("Не удалось разрешить плейсхолдер"));
    assert.equal(invalid.calls.some((call) => call.startsWith("git commit")), false);
    invalid.panel.handleInput("\r");
    await invalidRun;
  } finally {
    fs.rmSync(repoDir, { recursive: true, force: true });
  }
});

test("session shutdown settles a pending dialog and releases the panel", async () => {
  const fixture = setup();
  const running = fixture.start();
  await until(() => fixture.view().includes("Использовать существующее"));
  fixture.shutdown();
  await running;
  assert.equal(fixture.closes, 1);
  assert.equal(fixture.calls.some((call) => call.startsWith("git commit")), false);
});
