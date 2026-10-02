import assert from "node:assert/strict";
import test from "node:test";
import type { KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";
import { CURSOR_MARKER, stripTerminalSequences, visibleWidth, type TUI } from "@earendil-works/pi-tui";
import { MrEchatPanel } from "../shared/mr-echat-panel.ts";

function makePanel(rows = 24) {
	let renders = 0;
	const terminal = { rows, columns: 80 };
	const tui = {
		terminal,
		requestRender() { renders++; },
	} as unknown as TUI;
	const theme = {
		fg(color: string, text: string) {
			const codes: Record<string, string> = { accent: "31", dim: "2", text: "37", muted: "36", success: "32", warning: "33", error: "31" };
			return `\u001b[${codes[color] ?? "37"}m${text}\u001b[0m`;
		},
	} as unknown as Theme;
	const keybindings = {
		matches(data: string, key: string) {
			if (key === "tui.select.cancel") return data === "\u001b";
			if (key === "tui.select.confirm") return data === "\r" || data === "\n";
			return false;
		},
	} as unknown as KeybindingsManager;
	const panel = new MrEchatPanel(tui, theme, keybindings);
	panel.setContext("echat\u001b]0;ignored\u0007", "feature/界🙂");
	return {
		panel,
		resize(rows: number) { terminal.rows = rows; },
		get renders() { return renders; },
	};
}

function plain(panel: MrEchatPanel, width = 80): string[] {
	return panel.render(width).map((line) => stripTerminalSequences(line));
}

async function cancel(panel: MrEchatPanel): Promise<void> {
	panel.handleInput("\u001b");
}

test("keeps one fixed-height panel across every interaction stage", async () => {
	const { panel } = makePanel();
	panel.setResult("previous result");
	const heights = [panel.render(80).length];
	const selection = panel.select("Заголовок коммита", ["Сгенерировать название коммита", "Ввести своё"]);
	heights.push(panel.render(80).length);
	await cancel(panel);
	await selection;
	const input = panel.input("Введи название", "placeholder");
	heights.push(panel.render(80).length);
	await cancel(panel);
	await input;
	panel.progress("Генерирую", false);
	heights.push(panel.render(80).length);
	panel.setSteps(["git add", "git commit"]);
	heights.push(panel.render(80).length);
	panel.progress();
	const finish = panel.finish();
	heights.push(panel.render(80).length);
	panel.handleInput("\u001b");
	await finish;
	assert.deepEqual(new Set(heights).size, 1);
	panel.dispose();

	const short = makePanel(6).panel;
	short.setResult("short terminal");
	const shortHeights = [short.render(40).length];
	short.progress("busy", false);
	shortHeights.push(short.render(40).length);
	short.setSteps(["step"]);
	shortHeights.push(short.render(40).length);
	assert.deepEqual(new Set(shortHeights).size, 1);
	assert.equal(shortHeights[0], 6);
	short.dispose();
});

test("fits narrow widths and normalizes control sequences and Unicode", () => {
	const { panel } = makePanel();
	panel.setContext("repo\u001b[31m-red\u001b[0m\nname", "ветка");
	panel.setResult("Очень длинный заголовок界🙂e\u0301 с управляющими\tсимволами");
	panel.setSteps(["первый шаг界🙂", "второй шаг"]);
	for (const width of [1, 2, 3, 5, 8, 14, 20, 40, 80]) {
		for (const line of panel.render(width)) {
			assert.ok(visibleWidth(stripTerminalSequences(line)) <= width, `line exceeds width ${width}: ${line}`);
		}
	}
	const text = plain(panel, 40).join("\n");
	assert.doesNotMatch(text, /\x1b/);
	assert.doesNotMatch(text, /repo-redname/);
	panel.dispose();
});

test("returns exact select, input, and Russian confirm values", async () => {
	const { panel } = makePanel();
	const selection = panel.select("Действие", ["one", "two"]);
	panel.handleInput("\x1b[B");
	panel.handleInput("\r");
	assert.equal(await selection, "two");

	const input = panel.input("Название", "placeholder");
	panel.handleInput("тест界");
	panel.handleInput("\r");
	assert.equal(await input, "тест界");

	const confirm = panel.confirm("Подтвердить", "Продолжить?");
	panel.handleInput("\x1b[B");
	panel.handleInput("\r");
	assert.equal(await confirm, false);
	panel.dispose();
});

test("keeps the previous result and menu dimmed during busy work", async () => {
	const { panel } = makePanel();
	panel.setResult("generated title");
	const selection = panel.select("Действие", ["first action", "second action"]);
	const signal = panel.progress("Генерирую", true);
	assert.ok(signal);
	const rendered = panel.render(80).join("\n");
	assert.match(stripTerminalSequences(rendered), /generated title/);
	assert.match(stripTerminalSequences(rendered), /first action/);
	assert.match(rendered, /\u001b\[2m/);
	panel.handleInput("\r");
	assert.equal(signal!.aborted, false);
	panel.handleInput("\u001b");
	assert.equal(signal!.aborted, true);
	panel.progress();
	await selection;
	panel.dispose();
});

test("does not submit or mutate while busy, and reports honest non-cancellable waiting", () => {
	const { panel } = makePanel();
	panel.setResult("stable");
	const signal = panel.progress("Коммичу", false);
	panel.handleInput("\r");
	panel.handleInput("\u001b");
	assert.equal(signal?.aborted, false);
	assert.match(plain(panel).join("\n"), /Подожди, операция ещё выполняется/);
	assert.match(plain(panel).join("\n"), /stable/);
	panel.progress();
	panel.dispose();
});

test("retains selection meaning when title options are regenerated", async () => {
	const { panel } = makePanel();
	const first = panel.select("Заголовок", [
		"Использовать сгенерированный: first title",
		"Использовать существующий: old title",
	]);
	panel.handleInput("\x1b[B");
	panel.handleInput("\r");
	assert.equal(await first, "Использовать существующий: old title");

	const second = panel.select("Заголовок", [
		"Использовать сгенерированный: regenerated title",
		"Использовать существующий: newer title",
	]);
	const actions = plain(panel).join("\n");
	assert.match(actions, /→\s+Использовать существующий/);
	assert.match(plain(panel).join("\n"), /newer title/);
	await cancel(panel);
	await second;
	panel.dispose();
});

test("shows the new title while keeping the regeneration action selected", async () => {
	const { panel } = makePanel();
	const options = (title: string) => [`Использовать сгенерированный: ${title}`, "Сгенерировать другой вариант", "Ввести вручную"];
	const first = panel.select("Заголовок коммита", options("first title"));
	panel.handleInput("\x1b[B");
	panel.handleInput("\r");
	assert.equal(await first, "Сгенерировать другой вариант");
	panel.progress("Генерирую другой вариант", true);
	assert.match(plain(panel).join("\n"), /first title/);
	panel.progress();
	const next = panel.select("Заголовок коммита", options("new title"));
	const rendered = plain(panel).join("\n");
	assert.match(rendered, /new title/);
	assert.doesNotMatch(rendered, /first title/);
	assert.match(rendered, /→\s+Сгенерировать другой вариант/);
	panel.handleInput("\x1b");
	await next;
	panel.dispose();
});

test("keeps the selected action visible after a short-terminal resize", async () => {
	const fixture = makePanel();
	const { panel } = fixture;
	const pending = panel.select("Choose", ["one", "two", "three", "four"]);
	for (let i = 0; i < 3; i++) panel.handleInput("\x1b[B");
	fixture.resize(6);
	assert.equal(panel.render(30).length, 6);
	assert.match(plain(panel, 30).join("\n"), /→\s+four/);
	panel.handleInput("\r");
	assert.equal(await pending, "four");
	panel.dispose();
});

test("forwards focus to Input and emits CURSOR_MARKER", async () => {
	const { panel } = makePanel();
	const pending = panel.input("Введите", "placeholder");
	panel.focused = true;
	assert.ok(panel.render(80).some((line) => line.includes(CURSOR_MARKER)));
	panel.focused = false;
	assert.ok(panel.render(80).every((line) => !line.includes(CURSOR_MARKER)));
	await cancel(panel);
	await pending;
	panel.dispose();
});

test("finish shows the latest result and notification and is acknowledged by Enter/Esc", async () => {
	const { panel } = makePanel();
	panel.setResult("Very long previous commit title ".repeat(8));
	panel.notify("https://gitlab.example/mr/42", "info");
	const done = panel.finish();
	const rendered = plain(panel).join("\n");
	assert.match(rendered, /https:\/\/gitlab\.example\/mr\/42/);
	assert.doesNotMatch(rendered, /Very long previous/);
	panel.handleInput("\r");
	await done;
	assert.equal(panel.render(80).length, 14);
	panel.dispose();
});

test("dispose is idempotent, aborts generation, settles dialogs, and clears timer callbacks", async () => {
	const fixture = makePanel();
	const { panel } = fixture;
	const signal = panel.progress("Долгая генерация", true);
	const before = fixture.renders;
	panel.dispose();
	panel.dispose();
	assert.equal(signal?.aborted, true);
	await new Promise((resolve) => setTimeout(resolve, 1050));
	assert.equal(fixture.renders, before);
	assert.equal(await panel.select("after dispose", ["x"]), undefined);
	assert.equal(await panel.input("after dispose"), undefined);
	assert.equal(await panel.confirm("after dispose", "?"), false);
	await panel.finish();
});
