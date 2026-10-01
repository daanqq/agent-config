import assert from "node:assert/strict";
import test from "node:test";
import type {
	ExtensionAPI,
	ExtensionContext,
	ExtensionUIContext,
	KeybindingsManager,
} from "@earendil-works/pi-coding-agent";
import { ProcessTerminal, stripTerminalSequences, TuiMainScreen, visibleWidth } from "@earendil-works/pi-tui";
import editorUiExtension from "../00-ui-editor.ts";

type EditorFactory = NonNullable<Parameters<ExtensionUIContext["setEditorComponent"]>[0]>;
type Handler = (event: unknown, ctx: ExtensionContext) => unknown;

function setup(initialName?: string, mode = "tui") {
	let name = initialName;
	let factory: EditorFactory | undefined;
	let renders = 0;
	const handlers = new Map<string, Handler>();
	// Only the registration and UI surfaces used by this extension are stubbed.
	const pi = {
		on(event: string, handler: Handler) { handlers.set(event, handler); },
		getSessionName: () => name,
	} as unknown as ExtensionAPI;
	const ctx = {
		mode,
		ui: { setEditorComponent(next: EditorFactory) { factory = next; } },
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
