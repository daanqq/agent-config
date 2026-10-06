import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import type {
	ExtensionCommandContext,
	ExtensionAPI,
	ExtensionContext,
	ExtensionUIContext,
	KeybindingsManager,
} from "@earendil-works/pi-coding-agent";
import { ProcessTerminal, stripTerminalSequences, TuiMainScreen, visibleWidth } from "@earendil-works/pi-tui";
import editorUiExtension from "../00-ui-editor.ts";

type EditorFactory = NonNullable<Parameters<ExtensionUIContext["setEditorComponent"]>[0]>;
type Handler = (event: unknown, ctx: ExtensionContext) => unknown;
type Command = Parameters<ExtensionAPI["registerCommand"]>[1];

function setup(initialName?: string, mode = "tui", session = SessionManager.inMemory()) {
	let name = initialName;
	let factory: EditorFactory | undefined;
	let renders = 0;
	const handlers = new Map<string, Handler>();
	const commands = new Map<string, Command>();
	const notifications: Array<{ text: string; type?: string }> = [];
	// Only the registration and UI surfaces used by this extension are stubbed.
	const pi = {
		on(event: string, handler: Handler) { handlers.set(event, handler); },
		getSessionName: () => name,
		appendEntry: (type: string, data: unknown) => session.appendCustomEntry(type, data),
		registerCommand(command: string, definition: Command) { commands.set(command, definition); },
	} as unknown as ExtensionAPI;
	const ctx = {
		mode,
		sessionManager: session,
		ui: {
			setEditorComponent(next: EditorFactory) { factory = next; },
			notify(text: string, type?: string) { notifications.push({ text, type }); },
		},
	} as unknown as ExtensionContext;
	editorUiExtension(pi);
	handlers.get("session_start")?.({}, ctx);
	const tui = new TuiMainScreen(new ProcessTerminal());
	tui.requestRender = () => { renders++; };
	const plain = (text: string) => text;
	const editor = factory?.(tui, {
		borderColor: (text) => `\x1b[35m${text}\x1b[0m`,
		selectList: {
			selectedPrefix: plain, selectedText: plain, description: plain,
			scrollInfo: plain, noMatch: plain,
		},
	}, { matches: () => false } as unknown as KeybindingsManager);
	const top = (width: number) => stripTerminalSequences(editor!.render(width)[0]!);
	return {
		editor,
		top,
		session,
		notifications,
		rawTop: (width: number) => editor!.render(width)[0]!,
		input(text: string, source = "interactive") {
			handlers.get("input")?.({ text, source }, ctx);
			session.appendMessage({ role: "user", content: text, timestamp: Date.now() });
		},
		async taskurl(args: string) {
			await commands.get("taskurl")!.handler(args, ctx as ExtensionCommandContext);
		},
		reload() { handlers.get("session_start")?.({ reason: "reload" }, ctx); },
		startSession(next: SessionManager) {
			session = next;
			ctx.sessionManager = next;
			handlers.get("session_start")?.({ reason: "resume" }, ctx);
		},
		get taskEntries() { return session.getEntries().filter((entry) => entry.type === "custom"); },
		get renders() { return renders; },
		rename(next?: string) {
			name = next;
			handlers.get("session_info_changed")?.({}, ctx);
		},
		shutdown() { handlers.get("session_shutdown")?.({}, ctx); },
	};
}

test("aligns the session name with exactly one trailing border cell", () => {
	const { editor, top } = setup("UNIFIED AGENT CONFIG");
	assert.equal(top(60), "─".repeat(37) + " UNIFIED AGENT CONFIG ─");
	assert.equal(visibleWidth(editor!.render(60)[0]!), 60);
	assert.equal(stripTerminalSequences(editor!.render(60).at(-1)!), "─".repeat(60));
});

test("reads renamed and replacement session names at render time", () => {
	const fixture = setup("Original");
	fixture.rename("Renamed");
	assert.equal(fixture.renders, 1);
	assert.match(fixture.top(40), / Renamed ─$/);
	fixture.rename(undefined);
	assert.equal(fixture.top(40), "─".repeat(40));
	fixture.shutdown();
	fixture.rename("After shutdown");
	assert.equal(fixture.renders, 2);
});

test("keeps the native border when a session has no name", () => {
	for (const name of [undefined, "", "   "]) {
		assert.equal(setup(name).top(40), "─".repeat(40));
	}
});

test("fits narrow widths and truncates long Unicode names without shifting the suffix", () => {
	const fixture = setup("界🙂e\u0301".repeat(20));
	for (const width of [1, 2, 5, 6, 7, 14, 15, 16, 17, 20, 40, 80]) {
		const line = fixture.top(width);
		assert.equal(visibleWidth(line), width);
		if (width >= 7) assert.match(line, /^───.* .*… ─$/);
		else assert.equal(line, "─".repeat(width));
	}
});

test("removes terminal sequences and normalizes multiline names", () => {
	const { top } = setup("\x1b[31mRed\x1b[0m\n\tname\x1b]0;title\x07");
	assert.match(top(40), / Red name ─$/);
});

test("preserves native input and submission", () => {
	const { editor } = setup("Session");
	let submitted: string | undefined;
	editor!.onSubmit = (text) => { submitted = text; };
	editor!.handleInput("hello");
	assert.equal(editor!.getText(), "hello");
	editor!.handleInput("\r");
	assert.equal(submitted, "hello");
});

test("retains the native overflow indicator for scrolled editor content", () => {
	const { editor, top } = setup("Session");
	editor!.setText(Array.from({ length: 40 }, (_, i) => `line ${i}`).join("\n"));
	assert.match(top(80), /↑ \d+ more/);
	assert.match(top(80), / Session ─$/);
});

test("does not install a terminal editor in non-TUI modes", () => {
	for (const mode of ["rpc", "json", "print"]) assert.equal(setup("Session", mode).editor, undefined);
});

const taskUrl = (id: string) => `https://spacehub.esoft.tech/entity/${id}`;

test("captures the first valid user link, not extension input, and ignores all later mentions", () => {
	const fixture = setup("Session");
	fixture.input(taskUrl("T-999"), "extension");
	fixture.input("https://example.com/entity/T-1 https://spacehub.esoft.tech/entity/");
	assert.equal(fixture.taskEntries.length, 0);
	fixture.input(`Compare [task](${taskUrl("EUTP-170658")}) with <${taskUrl("T-2")}>.`);
	assert.match(fixture.top(80), / \[EUTP-170658\] Session ─$/);
	assert.equal(fixture.renders, 1);
	assert.equal(fixture.taskEntries.length, 1);
	assert.ok(fixture.rawTop(80).includes(`\x1b]8;;${taskUrl("EUTP-170658")}\x1b\\[EUTP-170658]\x1b]8;;\x1b\\`));
	fixture.input(taskUrl("EUTP-170658"));
	fixture.input(taskUrl("T-3"), "rpc");
	assert.equal(fixture.taskEntries.length, 1);
	assert.equal(fixture.renders, 1);
	assert.match(fixture.top(80), /\[EUTP-170658\]/);
});

test("supports other entity IDs, punctuation, query strings and unnamed sessions", () => {
	for (const text of [
		`${taskUrl("T-12345")}.`,
		`<${taskUrl("T-12345")}>`,
		`\`${taskUrl("T-12345")}\``,
		`(${taskUrl("T-12345")}),`,
		`${taskUrl("T-12345")}/?view=details#comments`,
	]) {
		const fixture = setup();
		fixture.input(text, "rpc");
		assert.match(fixture.top(80), / \[T-12345\] ─$/);
	}
});

test("only taskurl can replace the task, and invalid command arguments preserve it", async () => {
	const fixture = setup("Session");
	fixture.input(taskUrl("T-1"));
	await fixture.taskurl(`  ${taskUrl("EUTP-170658")}  `);
	assert.match(fixture.top(80), /\[EUTP-170658\]/);
	assert.equal(fixture.taskEntries.length, 2);
	for (const invalid of [
		"", "T-3", "http://spacehub.esoft.tech/entity/T-3",
		"https://spacehub.esoft.tech.evil/entity/T-3",
		"https://spacehub.esoft.tech/entity/", `${taskUrl("T-3")} extra`,
		`${taskUrl("T-3")}/nested`, `${taskUrl("T-3")}\x1b]8;;evil\x07`,
	]) {
		await fixture.taskurl(invalid);
		assert.equal(fixture.notifications.at(-1)?.type, "error");
		assert.match(fixture.top(80), /\[EUTP-170658\]/);
	}
	await fixture.taskurl(taskUrl("EUTP-170658"));
	fixture.input(taskUrl("T-4"));
	assert.equal(fixture.taskEntries.length, 2);
});

test("taskurl sets a task before the first user link", async () => {
	const fixture = setup();
	await fixture.taskurl(taskUrl("T-5"));
	assert.deepEqual(fixture.session.buildSessionContext().messages, []);
	fixture.input(taskUrl("T-6"));
	assert.match(fixture.top(80), /\[T-5\]/);
	assert.equal(fixture.taskEntries.length, 1);
});

test("restores the latest task from disk after reload, including across tree navigation", async () => {
	const directory = mkdtempSync(join(tmpdir(), "pi-ui-editor-test-"));
	try {
		const session = SessionManager.create(directory, directory);
		const fixture = setup("Session", "tui", session);
		fixture.input(taskUrl("T-1"));
		const firstLeaf = session.getLeafId()!;
		await fixture.taskurl(taskUrl("T-2"));
		fixture.reload();
		assert.match(fixture.top(80), /\[T-2\]/);
		fixture.input(taskUrl("T-3"));
		assert.equal(fixture.taskEntries.length, 2);
		session.branch(firstLeaf);
		const restored = setup("Session", "tui", SessionManager.open(session.getSessionFile()!));
		assert.match(restored.top(80), /\[T-2\]/);
		restored.input(taskUrl("T-4"));
		assert.equal(restored.taskEntries.length, 2);
	} finally {
		rmSync(directory, { recursive: true, force: true });
	}
});

test("resets task state when switching to another session", () => {
	const fixture = setup("Session");
	fixture.input(taskUrl("T-1"));
	fixture.startSession(SessionManager.inMemory());
	assert.doesNotMatch(fixture.top(80), /\[T-1\]/);
	fixture.input(taskUrl("T-2"));
	assert.match(fixture.top(80), /\[T-2\]/);
	assert.equal(fixture.taskEntries.length, 1);
});

test("validates stored URLs and restores the latest valid override", () => {
	const session = SessionManager.inMemory();
	session.appendCustomEntry("other-extension", taskUrl("T-9"));
	session.appendCustomEntry("ui-editor-task-url", taskUrl("T-1"));
	session.appendCustomEntry("ui-editor-task-url", taskUrl("T-2"));
	session.appendCustomEntry("ui-editor-task-url", { url: "untrusted" });
	session.appendCustomEntry("ui-editor-task-url", "\x1b]8;;evil\x07");
	assert.match(setup("Session", "tui", session).top(80), /\[T-2\]/);
});

test("fits task hyperlinks and long session names within every narrow width", () => {
	const fixture = setup("界🙂e\u0301".repeat(20));
	fixture.input(taskUrl("EUTP-170658"));
	for (const width of [1, 2, 5, 6, 7, 14, 15, 16, 17, 20, 40, 80]) {
		assert.equal(visibleWidth(fixture.rawTop(width)), width);
		assert.equal(visibleWidth(fixture.top(width)), width);
		if (width >= 7) assert.match(fixture.top(width), /^───.* .*… ─$/);
		else assert.equal(fixture.top(width), "─".repeat(width));
		const raw = fixture.rawTop(width);
		if (raw.includes(`\x1b]8;;${taskUrl("EUTP-170658")}`)) {
			const close = raw.lastIndexOf("\x1b]8;;\x1b\\");
			assert.ok(close >= 0 && close < raw.lastIndexOf(" ─"));
		}
	}
});

test("persists task state in non-TUI modes without installing an editor", async () => {
	for (const mode of ["rpc", "json", "print"]) {
		const fixture = setup("Session", mode);
		fixture.input(taskUrl("T-1"), "rpc");
		await fixture.taskurl(taskUrl("T-2"));
		assert.equal(fixture.editor, undefined);
		assert.equal(fixture.taskEntries.length, 2);
		const tui = setup("Session", "tui", fixture.session);
		assert.match(tui.top(80), /\[T-2\]/);
	}
});
