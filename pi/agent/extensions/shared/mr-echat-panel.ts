import type { KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";
import {
	Input,
	type Component,
	type Focusable,
	type SelectItem,
	SelectList,
	type TUI,
	stripTerminalSequences,
	truncateToWidth,
	visibleWidth,
	wrapTextWithAnsi,
} from "@earendil-works/pi-tui";

const PANEL_HEIGHT = 14;
const MIN_PANEL_HEIGHT = 5;
const PROGRESS_FRAMES = ["·", "··", "···"];
const RESULT_LINES = 2;
const ACTION_LINES = 4;
const TITLE_OPTIONS = [
	["Использовать сгенерированный: ", "Использовать сгенерированный"],
	["Использовать существующий: ", "Использовать существующий"],
	["Использовать существующее сообщение: ", "Использовать существующее сообщение"],
] as const;

type Notification = {
	message: string;
	type: "info" | "warning" | "error";
};

type SelectDialog = {
	kind: "select";
	title: string;
	resolve: (value: string | undefined) => void;
	selected: SelectItem | undefined;
};

type InputDialog = {
	kind: "input";
	title: string;
	resolve: (value: string | undefined) => void;
};

type Dialog = SelectDialog | InputDialog;

function normalizeDisplayText(value: string): string {
	return stripTerminalSequences(value)
		.normalize("NFC")
		.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
		.replace(/\s+/g, " ")
		.trim();
}

function titleOption(value: string): { label: string; title?: string; meaning: string } {
	const clean = normalizeDisplayText(value);
	for (const [prefix, label] of TITLE_OPTIONS) {
		if (clean.startsWith(prefix)) {
			return {
				label,
				title: clean.slice(prefix.length).trim(),
				meaning: label,
			};
		}
	}
	return { label: clean, meaning: clean };
}

function sameItemMeaning(left: string, right: string): boolean {
	return titleOption(left).meaning === titleOption(right).meaning;
}

export class MrEchatPanel implements Component, Focusable {
	private readonly tui: TUI;
	private readonly theme: Theme;
	private readonly keybindings: KeybindingsManager;
	private _focused = false;
	private disposed = false;
	private repo = "";
	private branch = "";
	private result = "";
	private steps: string[] | undefined;
	private notification: Notification | undefined;
	private dialog: Dialog | undefined;
	private inputComponent: Input | undefined;
	private menu: SelectList | undefined;
	private menuItems: SelectItem[] = [];
	private menuVisible = ACTION_LINES;
	private lastSelectionMeaning: string | undefined;
	private finished = false;
	private finishResolver: (() => void) | undefined;
	private busy = false;
	private cancellable = false;
	private cancelRequested = false;
	private progressMessage = "Выполняю операцию";
	private progressStartedAt = 0;
	private progressFrame = 0;
	private generationController: AbortController | undefined;
	private progressTimer: ReturnType<typeof setInterval> | undefined;

	constructor(tui: TUI, theme: Theme, keybindings: KeybindingsManager) {
		this.tui = tui;
		this.theme = theme;
		this.keybindings = keybindings;
	}

	get focused(): boolean {
		return this._focused;
	}

	set focused(value: boolean) {
		this._focused = value;
		if (this.inputComponent) this.inputComponent.focused = value;
	}

	select(title: string, options: string[]): Promise<string | undefined> {
		if (this.disposed || this.finished || options.length === 0) return Promise.resolve(undefined);
		this.cancelDialog();
		this.steps = undefined;
		const items = options.map((value): SelectItem => {
			const parsed = titleOption(value);
			return { value, label: parsed.label };
		});
		this.menuItems = items;
		this.menu = this.createSelectList(items);
		const selectedIndex = this.lastSelectionMeaning
			? items.findIndex((item) => sameItemMeaning(item.value, this.lastSelectionMeaning!))
			: -1;
		this.menu.setSelectedIndex(selectedIndex >= 0 ? selectedIndex : 0);
		const selected = items[selectedIndex >= 0 ? selectedIndex : 0];
		const candidate = options.map(titleOption).find((option) => option.title);
		if (candidate?.title) this.result = candidate.title;
		this.updateTitleResult(selected?.value);
		return new Promise<string | undefined>((resolve) => {
			const prompt = title === "Заголовок коммита" ? "Выбери сообщение коммита" : title;
			this.dialog = { kind: "select", title: normalizeDisplayText(prompt), resolve, selected };
			this.requestRender();
		});
	}

	input(title: string, placeholder?: string): Promise<string | undefined> {
		if (this.disposed || this.finished) return Promise.resolve(undefined);
		this.cancelDialog();
		this.steps = undefined;
		const input = new Input({ placeholder: normalizeDisplayText(placeholder ?? "") });
		input.focused = this._focused;
		this.inputComponent = input;
		return new Promise<string | undefined>((resolve) => {
			this.dialog = { kind: "input", title: normalizeDisplayText(title), resolve };
			this.requestRender();
		});
	}

	async confirm(title: string, message: string): Promise<boolean> {
		return await this.select(`${title}. ${message}`, ["Да", "Нет"]) === "Да";
	}
	setContext(repo: string, branch?: string): void {
		if (this.disposed) return;
		this.repo = normalizeDisplayText(repo);
		this.branch = normalizeDisplayText(branch ?? "");
		this.requestRender();
	}

	setResult(text: string): void {
		if (this.disposed) return;
		this.result = normalizeDisplayText(text);
		this.requestRender();
	}

	setSteps(steps: string[]): void {
		if (this.disposed) return;
		this.cancelDialog();
		this.menu = undefined;
		this.menuItems = [];
		this.steps = steps.map(normalizeDisplayText).filter(Boolean);
		this.requestRender();
	}

	progress(message?: string, cancellable = false): AbortSignal | undefined {
		if (this.disposed || this.finished) return undefined;
		if (message === undefined) {
			this.stopProgressTimer();
			this.busy = false;
			this.cancellable = false;
			this.cancelRequested = false;
			this.generationController = undefined;
			this.requestRender();
			return undefined;
		}

		this.cancelDialog();
		this.stopProgressTimer();
		this.busy = true;
		this.cancellable = cancellable;
		this.cancelRequested = false;
		this.progressMessage = normalizeDisplayText(message) || "Выполняю операцию";
		this.progressFrame = 0;
		this.progressStartedAt = Date.now();
		const controller = new AbortController();
		this.generationController = controller;
		this.progressTimer = setInterval(() => {
			if (this.disposed || this.generationController !== controller) return;
			this.progressFrame = (this.progressFrame + 1) % PROGRESS_FRAMES.length;
			this.requestRender();
		}, 1000);
		this.progressTimer.unref?.();
		this.requestRender();
		return controller.signal;
	}

	notify(message: string, type: "info" | "warning" | "error" = "info"): void {
		if (this.disposed) return;
		this.notification = { message: normalizeDisplayText(message), type };
		this.requestRender();
	}

	finish(): Promise<void> {
		if (this.disposed || this.finished) return Promise.resolve();
		this.cancelDialog();
		this.stopProgressTimer();
		this.busy = false;
		this.cancellable = false;
		this.cancelRequested = false;
		this.finished = true;
		this.menu = undefined;
		this.menuItems = [];
		this.requestRender();
		return new Promise<void>((resolve) => {
			this.finishResolver = resolve;
		});
	}

	dispose(): void {
		if (this.disposed) return;
		this.disposed = true;
		this.stopProgressTimer();
		this.generationController?.abort();
		this.generationController = undefined;
		this.cancelDialog();
		this.finished = true;
		this.finishResolver?.();
		this.finishResolver = undefined;
		this.menu = undefined;
		this.inputComponent = undefined;
	}

	render(width: number): string[] {
		const safeWidth = Math.max(1, Math.floor(width));
		const { height, bordered, resultSlots, actionSlots, gaps } = this.layout();
		const lines: string[] = [];
		const blank = " ".repeat(safeWidth);
		const border = () => this.theme.fg("accent", "─".repeat(safeWidth));

		if (bordered) lines.push(border());
		lines.push(this.fit(this.headerText(), safeWidth, (text) => this.theme.fg("accent", text)));
		if (gaps >= 1) lines.push(blank);
		lines.push(...this.renderResult(safeWidth, resultSlots));
		if (gaps >= 2) lines.push(blank);
		lines.push(...this.renderActions(safeWidth, actionSlots));
		if (gaps >= 3) lines.push(blank);
		while (lines.length < height - 2 - Number(bordered)) lines.push(blank);
		lines.push(this.fit(this.statusText(), safeWidth, (text) => this.statusStyle(text)));
		lines.push(this.fit(this.hintText(), safeWidth, (text) => this.theme.fg("dim", text)));
		if (bordered) lines.push(border());
		return lines.map((line) => this.fit(line, safeWidth));
	}

	handleInput(data: string): void {
		if (this.disposed) return;
		if (this.finished) {
			if (this.isCancel(data) || this.isConfirm(data)) this.acknowledgeFinish();
			return;
		}
		if (this.busy) {
			if (this.cancellable && this.isCancel(data)) {
				this.generationController?.abort();
				this.cancelRequested = true;
				this.requestRender();
			}
			return;
		}

		if (this.dialog?.kind === "input") {
			if (this.isCancel(data)) {
				this.cancelDialog();
			} else if (this.isConfirm(data)) {
				const value = this.inputComponent?.getValue() ?? "";
				this.resolveInput(value);
			} else {
				this.inputComponent?.handleInput(data);
				this.requestRender();
			}
			return;
		}

		if (this.dialog?.kind === "select") {
			if (this.isCancel(data)) {
				this.cancelDialog();
			} else if (this.isConfirm(data)) {
				this.chooseSelected();
			} else {
				this.menu?.handleInput(data);
				this.requestRender();
			}
		}
	}

	invalidate(): void {
		this.menu?.invalidate();
		this.inputComponent?.invalidate();
	}

	private createSelectList(items: SelectItem[]): SelectList {
		this.menuVisible = this.layout().actionSlots;
		const list = new SelectList(items, this.menuVisible, {
			selectedPrefix: (text) => this.menuStyle(text, true),
			selectedText: (text) => this.menuStyle(text, true),
			description: (text) => this.menuStyle(text),
			scrollInfo: (text) => this.menuStyle(text),
			noMatch: (text) => this.menuStyle(text),
		});
		list.onSelectionChange = (item) => this.selectionChanged(item);
		list.onSelect = (item) => this.chooseItem(item);
		list.onCancel = () => this.cancelDialog();
		return list;
	}

	private selectionChanged(item: SelectItem): void {
		this.lastSelectionMeaning = titleOption(item.value).meaning;
		if (this.dialog?.kind === "select") {
			this.dialog.selected = item;
			this.updateTitleResult(item.value);
		}
		this.requestRender();
	}

	private chooseSelected(): void {
		const selected = this.dialog?.kind === "select"
			? this.dialog.selected
			: undefined;
		if (selected) this.chooseItem(selected);
	}

	private chooseItem(item: SelectItem): void {
		if (this.dialog?.kind !== "select") return;
		this.selectionChanged(item);
		const dialog = this.dialog;
		this.dialog = undefined;
		dialog.resolve(item.value);
		this.requestRender();
	}

	private resolveInput(value: string): void {
		if (this.dialog?.kind !== "input") return;
		const dialog = this.dialog;
		this.dialog = undefined;
		this.inputComponent = undefined;
		dialog.resolve(value);
		this.requestRender();
	}

	private cancelDialog(): void {
		if (!this.dialog) return;
		const dialog = this.dialog;
		this.dialog = undefined;
		this.inputComponent = undefined;
		dialog.resolve(undefined);
		this.requestRender();
	}

	private updateTitleResult(value: string | undefined): void {
		if (!value) return;
		const parsed = titleOption(value);
		if (parsed.title) this.result = parsed.title;
	}

	private headerText(): string {
		const parts = ["mr-echat"];
		if (this.repo) parts.push(this.repo);
		if (this.branch) parts.push(this.branch);
		return parts.join(" · ");
	}

	private statusText(): string {
		if (this.finished) return this.notification?.type === "error" ? "Не удалось завершить команду" : "Сценарий завершён";
		if (this.busy) {
			const elapsed = Math.floor(Math.max(0, Date.now() - this.progressStartedAt) / 1000);
			const suffix = this.cancelRequested ? " · отмена запрошена, жду завершения" : ` · ${elapsed}с`;
			return `${this.progressMessage}${PROGRESS_FRAMES[this.progressFrame]}${suffix}`;
		}
		if (this.dialog) return this.dialog.title;
		if (this.notification) return this.notification.message;
		return "Готово к следующему действию";
	}

	private hintText(): string {
		if (this.finished) return "Enter/Esc - вернуться в чат";
		if (this.busy) {
			if (this.cancelRequested) return "Жду завершения операции";
			return this.cancellable ? "Esc - отменить генерацию" : "Подожди, операция ещё выполняется";
		}
		if (this.dialog?.kind === "input") return "Enter - подтвердить · Esc - отмена";
		if (this.dialog) return "↑↓ - выбрать · Enter - подтвердить · Esc - отмена";
		return "";
	}

	private renderResult(width: number, slots: number): string[] {
		if (this.dialog?.kind === "input") {
			const inputLine = this.fit(this.inputComponent?.render(width)[0] ?? "", width);
			return [inputLine, ...Array(Math.max(0, slots - 1)).fill(" ".repeat(width))];
		}
		if (this.finished) return this.textLines(this.notification?.message ?? this.result, width, slots);
		return this.textLines(this.result, width, slots);
	}

	private renderActions(width: number, slots: number): string[] {
		let source: string[] = [];
		if (this.steps) {
			source = this.steps.map((step) => `• ${step}`);
		} else if (this.menu) {
			if (this.menuVisible !== slots) {
				const selected = this.menu.getSelectedItem();
				this.menu = this.createSelectList(this.menuItems);
				this.menu.setSelectedIndex(Math.max(0, this.menuItems.findIndex((item) => item.value === selected?.value)));
			}
			source = this.menu.render(width);
		}
		const result = source.slice(0, slots).map((line) => this.fit(line, width));
		while (result.length < slots) result.push(" ".repeat(width));
		return result;
	}

	private textLines(value: string, width: number, slots: number): string[] {
		const clean = normalizeDisplayText(value);
		const wrapped = clean ? wrapTextWithAnsi(clean, width) : [];
		const result = wrapped.slice(0, slots).map((line) => this.fit(line, width));
		if (wrapped.length > slots && slots > 0) {
			result[slots - 1] = this.fit(truncateToWidth(wrapped[slots - 1]!, Math.max(0, width - 1), "") + "…", width);
		}
		while (result.length < slots) result.push(" ".repeat(width));
		return result;
	}

	private statusStyle(text: string): string {
		if (this.finished) return this.theme.fg(this.notification?.type === "error" ? "error" : "muted", text);
		if (this.busy) return this.theme.fg(this.cancelRequested ? "warning" : "accent", text);
		if (this.notification) return this.theme.fg(this.notification.type === "info" ? "muted" : this.notification.type, text);
		return this.theme.fg("muted", text);
	}

	private menuStyle(text: string, selected = false): string {
		const inactive = this.busy || this.dialog?.kind === "input";
		return this.theme.fg(inactive ? "dim" : selected ? "accent" : "text", text);
	}

	private fit(value: string, width: number, style?: (text: string) => string): string {
		if (width <= 0) return "";
		const truncated = truncateToWidth(value, width, "");
		const rendered = style ? style(truncated) : truncated;
		return rendered + " ".repeat(Math.max(0, width - visibleWidth(rendered)));
	}

	private layout() {
		const height = this.panelHeight();
		const bordered = height >= 10;
		const resultSlots = height >= 8 ? RESULT_LINES : 1;
		const actionSlots = Math.max(1, Math.min(ACTION_LINES, height - 3 - resultSlots - 2 * Number(bordered)));
		const gaps = height - 3 - resultSlots - actionSlots - 2 * Number(bordered);
		return { height, bordered, resultSlots, actionSlots, gaps };
	}

	private panelHeight(): number {
		const rows = this.tui.terminal?.rows;
		if (typeof rows !== "number" || !Number.isFinite(rows) || rows <= 0) return PANEL_HEIGHT;
		return Math.max(MIN_PANEL_HEIGHT, Math.min(PANEL_HEIGHT, Math.floor(rows)));
	}

	private stopProgressTimer(): void {
		if (this.progressTimer) {
			clearInterval(this.progressTimer);
			this.progressTimer = undefined;
		}
	}

	private requestRender(): void {
		if (!this.disposed) this.tui.requestRender();
	}

	private isCancel(data: string): boolean {
		return data === "\u001b" || this.keybindings.matches(data, "tui.select.cancel");
	}

	private isConfirm(data: string): boolean {
		return data === "\r" || data === "\n" || this.keybindings.matches(data, "tui.select.confirm");
	}

	private acknowledgeFinish(): void {
		const resolver = this.finishResolver;
		this.finishResolver = undefined;
		resolver?.();
	}
}

