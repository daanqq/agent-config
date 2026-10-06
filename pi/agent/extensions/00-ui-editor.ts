import {
	CustomEditor,
	type ExtensionAPI,
	type ExtensionContext,
	type KeybindingsManager,
} from "@earendil-works/pi-coding-agent";
import {
	hyperlink,
	stripTerminalSequences,
	truncateToWidth,
	visibleWidth,
	type EditorTheme,
	type TUI,
} from "@earendil-works/pi-tui";

const TASK_URL_PREFIX = "https://spacehub.esoft.tech/entity/";
const TASK_ENTRY_TYPE = "ui-editor-task-url";

type TaskLink = { id: string; url: string };

function parseTaskUrl(value: unknown): TaskLink | undefined {
	if (typeof value !== "string" || !value.startsWith(TASK_URL_PREFIX)
		|| /[\s\x00-\x1f\x7f-\x9f]/.test(value)) return undefined;
	try {
		const url = new URL(value);
		const id = url.pathname.match(/^\/entity\/([A-Za-z0-9][A-Za-z0-9_-]*)\/?$/)?.[1];
		if (id) return { id, url: url.href };
	} catch {
		return undefined;
	}
	return undefined;
}

function firstTaskLink(text: string): TaskLink | undefined {
	const links = text.matchAll(/https:\/\/spacehub\.esoft\.tech\/entity\/[^\s<>"'`\)\]\}]+/g);
	for (const [link] of links) {
		const task = parseTaskUrl(link.replace(/[.,;:!?]+$/, ""));
		if (task) return task;
	}
	return undefined;
}

class SessionNameEditor extends CustomEditor {
	constructor(
		tui: TUI,
		theme: EditorTheme,
		keybindings: KeybindingsManager,
		private readonly getSessionName: () => string | undefined,
		private readonly getTask: () => TaskLink | undefined,
	) {
		super(tui, theme, keybindings, { embedWorkingStatus: true });
	}

	protected override renderTopBorder(width: number, hiddenLineCount: number): string {
		const name = stripTerminalSequences(this.getSessionName() ?? "")
			.replace(/[\x00-\x1f\x7f-\x9f]/g, " ")
			.replace(/\s+/g, " ")
			.trim();
		const task = this.getTask();
		const title = [task ? hyperlink(`[${task.id}]`, task.url) : "", name].filter(Boolean).join(" ");
		const nameWidth = width - visibleWidth("───  ─");
		if (!title || nameWidth < 1) return super.renderTopBorder(width, hiddenLineCount);

		const label = ` ${truncateToWidth(title, nameWidth, "…")} ─`;
		return super.renderTopBorder(width - visibleWidth(label), hiddenLineCount) + this.borderColor(label);
	}
}

export default function editorUiExtension(pi: ExtensionAPI) {
	let requestRender: (() => void) | undefined;
	let task: TaskLink | undefined;

	function setTask(next: TaskLink) {
		if (task?.url === next.url) return;
		pi.appendEntry(TASK_ENTRY_TYPE, next.url);
		task = next;
		requestRender?.();
	}

	function restoreTask(ctx: ExtensionContext) {
		task = undefined;
		// The task belongs to the session, not the current /tree branch.
		for (const entry of ctx.sessionManager.getEntries()) {
			if (entry.type !== "custom" || entry.customType !== TASK_ENTRY_TYPE) continue;
			const restored = parseTaskUrl(entry.data);
			if (restored) task = restored;
		}
	}

	pi.on("input", (event) => {
		if (task || event.source === "extension") return;
		const first = firstTaskLink(event.text);
		if (first) setTask(first);
	});

	pi.registerCommand("taskurl", {
		description: "Set or replace the session's SpaceHub task URL",
		handler: async (args, ctx) => {
			const next = parseTaskUrl(args.trim());
			if (!next) {
				ctx.ui.notify(`Usage: /taskurl ${TASK_URL_PREFIX}EUTP-170658`, "error");
				return;
			}
			setTask(next);
			ctx.ui.notify(`Session task: ${next.id}`, "info");
		},
	});

	pi.on("session_start", (_event, ctx) => {
		requestRender = undefined;
		restoreTask(ctx);
		if (ctx.mode !== "tui") return;
		ctx.ui.setEditorComponent((tui, theme, keybindings) => {
			requestRender = () => tui.requestRender();
			return new SessionNameEditor(tui, theme, keybindings, () => pi.getSessionName(), () => task);
		});
	});

	pi.on("session_info_changed", () => requestRender?.());
	pi.on("session_shutdown", () => { requestRender = undefined; });
}
