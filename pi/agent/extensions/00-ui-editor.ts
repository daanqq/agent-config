import {
	CustomEditor,
	type ExtensionAPI,
	type KeybindingsManager,
} from "@earendil-works/pi-coding-agent";
import {
	stripTerminalSequences,
	truncateToWidth,
	visibleWidth,
	type EditorTheme,
	type TUI,
} from "@earendil-works/pi-tui";

class SessionNameEditor extends CustomEditor {
	constructor(
		tui: TUI,
		theme: EditorTheme,
		keybindings: KeybindingsManager,
		private readonly getSessionName: () => string | undefined,
	) {
		super(tui, theme, keybindings, { embedWorkingStatus: true });
	}

	protected override renderTopBorder(width: number, hiddenLineCount: number): string {
		const name = stripTerminalSequences(this.getSessionName() ?? "")
			.replace(/[\x00-\x1f\x7f-\x9f]/g, " ")
			.replace(/\s+/g, " ")
			.trim();
		const nameWidth = width - visibleWidth("───  ─");
		if (!name || nameWidth < 1) return super.renderTopBorder(width, hiddenLineCount);

		const label = ` ${truncateToWidth(name, nameWidth, "…")} ─`;
		return super.renderTopBorder(width - visibleWidth(label), hiddenLineCount) + this.borderColor(label);
	}
}

export default function editorUiExtension(pi: ExtensionAPI) {
	let requestRender: (() => void) | undefined;

	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		ctx.ui.setEditorComponent((tui, theme, keybindings) => {
			requestRender = () => tui.requestRender();
			return new SessionNameEditor(tui, theme, keybindings, () => pi.getSessionName());
		});
	});

	pi.on("session_info_changed", () => requestRender?.());
	pi.on("session_shutdown", () => { requestRender = undefined; });
}
