import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { homedir } from "node:os";
import { join } from "node:path";
import {
	appendCodexDiagnosticRecord,
	createCodexDiagnosticRecord,
	formatTransportFailure,
	type CodexDiagnosticRecord,
} from "./diagnostics.ts";

function diagnosticLogPath(): string {
	const configured = process.env.PI_CODEX_WS_DIAGNOSTICS_FILE?.trim();
	if (configured) return configured;
	const cacheDir = process.env.XDG_CACHE_HOME?.trim() || join(homedir(), ".cache");
	return join(cacheDir, "pi", "codex-ws-diagnostics.jsonl");
}

export default function codexWebSocketDiagnostics(pi: ExtensionAPI) {
	const logPath = diagnosticLogPath();
	let latestRecord: CodexDiagnosticRecord | undefined;

	pi.on("message_end", async (event, ctx) => {
		if (event.message.role !== "assistant") return;
		const record = createCodexDiagnosticRecord(event.message, {
			sessionId: ctx.sessionManager.getSessionId(),
			sessionFile: ctx.sessionManager.getSessionFile(),
		});
		if (!record) return;

		try {
			await appendCodexDiagnosticRecord(logPath, record);
			latestRecord = record;
		} catch (error) {
			if (ctx.hasUI) {
				ctx.ui.notify(
					`Failed to write Codex diagnostics: ${error instanceof Error ? error.message : String(error)}`,
					"error",
				);
			}
			return;
		}

		const failure = formatTransportFailure(record);
		if (failure && ctx.hasUI) {
			ctx.ui.notify(`Codex WebSocket: ${failure}\nLog: ${logPath}`, "warning");
		}
	});

	pi.registerCommand("codex-ws:diagnostics", {
		description: "Show the Codex WebSocket diagnostic log and latest captured event",
		handler: async (_args, ctx) => {
			const latest = latestRecord
				? `\nLatest: ${formatTransportFailure(latestRecord) ?? latestRecord.errorMessage ?? latestRecord.kind}`
				: "\nNo Codex diagnostic event captured in this Pi process.";
			ctx.ui.notify(`Codex diagnostic log: ${logPath}${latest}`, "info");
		},
	});
}
