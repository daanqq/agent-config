import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Spacer, type TUI } from "@earendil-works/pi-tui";

const BASELINE_SCROLL_LINES = 5;
const WIDGET_KEY = "fullscreen-scroll-speed";

type ConfigurableFullscreenTui = TUI & {
	wheelScrollLines: number;
};

export function increaseFullscreenScrollSpeed(tui: TUI): boolean {
	if (tui.mode !== "fullscreen") return false;

	const fullscreenTui = tui as ConfigurableFullscreenTui;
	if (typeof fullscreenTui.wheelScrollLines !== "number") return false;

	// Pi applies its built-in Alt multiplier to this baseline value.
	fullscreenTui.wheelScrollLines = BASELINE_SCROLL_LINES;
	return true;
}

export default function fullscreenScrollSpeedExtension(pi: ExtensionAPI) {
	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;

		// Widget factories are the public extension seam that exposes the active TUI.
		ctx.ui.setWidget(WIDGET_KEY, (tui) => {
			if (tui.mode === "fullscreen" && !increaseFullscreenScrollSpeed(tui)) {
				ctx.ui.notify("Could not increase fullscreen scroll speed for this Pi version.", "warning");
			}

			return new Spacer(0);
		});
	});
}
