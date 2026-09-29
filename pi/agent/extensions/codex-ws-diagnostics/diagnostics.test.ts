import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import codexWebSocketDiagnostics from "./index.ts";
import {
	appendCodexDiagnosticRecord,
	createCodexDiagnosticRecord,
	formatTransportFailure,
} from "./diagnostics.ts";

const baseMessage = {
	role: "assistant",
	api: "openai-codex-responses",
	provider: "openai-codex",
	model: "gpt-5.6-sol",
	timestamp: 123,
	stopReason: "stop",
};

test("ignores successful Codex messages without a transport diagnostic", () => {
	assert.equal(createCodexDiagnosticRecord(baseMessage, { sessionId: "session-1", now: 1 }), undefined);
});

test("captures WebSocket failure metadata without copying payloads or message content", () => {
	const record = createCodexDiagnosticRecord({
		...baseMessage,
		content: [{ type: "text", text: "private response" }],
		diagnostics: [{
			type: "provider_transport_failure",
			timestamp: 456,
			error: {
				name: "WebSocketCloseError",
				message: "WebSocket closed 1006",
				code: 1006,
				stack: "safe stack",
			},
			details: {
				configuredTransport: "websocket-cached",
				fallbackTransport: "sse",
				eventsEmitted: false,
				phase: "before_message_stream_start",
				requestBytes: 2048,
				requestPayload: "private prompt",
			},
		}],
	}, {
		sessionId: "session-1",
		sessionFile: "/tmp/session.jsonl",
		now: 1_000,
	});

	assert.ok(record);
	assert.equal(record.kind, "websocket_transport_failure");
	assert.equal(record.recordedAt, "1970-01-01T00:00:01.000Z");
	assert.equal(record.transportFailures[0]?.error?.code, 1006);
	assert.equal(record.transportFailures[0]?.details?.requestBytes, 2048);
	assert.equal("requestPayload" in (record.transportFailures[0]?.details ?? {}), false);
	assert.equal("content" in record, false);
	assert.equal(
		formatTransportFailure(record),
		"WebSocket closed 1006; before stream; fallback: SSE",
	);
});

test("captures final Codex provider errors even without a WebSocket diagnostic", () => {
	const record = createCodexDiagnosticRecord({
		...baseMessage,
		stopReason: "error",
		errorMessage: "Codex error: rate_limit_exceeded",
	}, { sessionId: "session-2", now: 2_000 });

	assert.ok(record);
	assert.equal(record.kind, "codex_provider_error");
	assert.equal(record.errorMessage, "Codex error: rate_limit_exceeded");
	assert.deepEqual(record.transportFailures, []);
});

test("appends private JSONL records and creates the parent directory", async () => {
	const root = await mkdtemp(join(tmpdir(), "codex-ws-diagnostics-test-"));
	const path = join(root, "nested", "events.jsonl");
	const record = createCodexDiagnosticRecord({
		...baseMessage,
		stopReason: "error",
		errorMessage: "WebSocket error",
	}, { sessionId: "session-3", now: 3_000 });
	assert.ok(record);

	try {
		await appendCodexDiagnosticRecord(path, record);
		await appendCodexDiagnosticRecord(path, record);
		const lines = (await readFile(path, "utf8")).trim().split("\n");
		assert.equal(lines.length, 2);
		assert.deepEqual(JSON.parse(lines[0]!), JSON.parse(JSON.stringify(record)));
		if (process.platform !== "win32") {
			assert.equal((await stat(path)).mode & 0o777, 0o600);
		}
	} finally {
		await rm(root, { recursive: true, force: true });
	}
});

test("extension logs and reports a finalized WebSocket transport failure", async () => {
	const root = await mkdtemp(join(tmpdir(), "codex-ws-extension-test-"));
	const path = join(root, "events.jsonl");
	const previousPath = process.env.PI_CODEX_WS_DIAGNOSTICS_FILE;
	type MessageEndHandler = (event: { message: typeof message }, ctx: typeof context) => Promise<void>;
	type CommandHandler = (args: string, ctx: typeof context) => Promise<void>;
	let messageEnd: MessageEndHandler | undefined;
	let command: CommandHandler | undefined;
	const notifications: Array<{ message: string; level: string }> = [];
	const context = {
		hasUI: true,
		sessionManager: {
			getSessionId: () => "session-extension",
			getSessionFile: () => "/tmp/session-extension.jsonl",
		},
		ui: {
			notify: (message: string, level: string) => notifications.push({ message, level }),
		},
	};
	const message = {
		...baseMessage,
		diagnostics: [{
			type: "provider_transport_failure",
			error: { message: "WebSocket idle timeout after 120000ms" },
			details: {
				phase: "after_message_stream_start",
				eventsEmitted: true,
			},
		}],
	};

	try {
		process.env.PI_CODEX_WS_DIAGNOSTICS_FILE = path;
		const pi = {
			on: (event: string, handler: unknown) => {
				if (event === "message_end") messageEnd = handler as MessageEndHandler;
			},
			registerCommand: (name: string, definition: { handler: unknown }) => {
				if (name === "codex-ws:diagnostics") command = definition.handler as CommandHandler;
			},
		};
		codexWebSocketDiagnostics(pi as unknown as Parameters<typeof codexWebSocketDiagnostics>[0]);
		assert.ok(messageEnd);
		assert.ok(command);

		await messageEnd({ message }, context);
		const persisted = JSON.parse((await readFile(path, "utf8")).trim());
		assert.equal(persisted.sessionId, "session-extension");
		assert.equal(persisted.transportFailures[0].error.message, "WebSocket idle timeout after 120000ms");
		assert.match(notifications[0]?.message ?? "", /during stream/);
		assert.equal(notifications[0]?.level, "warning");

		await command("", context);
		assert.match(notifications[1]?.message ?? "", /Codex diagnostic log:/);
	} finally {
		if (previousPath === undefined) delete process.env.PI_CODEX_WS_DIAGNOSTICS_FILE;
		else process.env.PI_CODEX_WS_DIAGNOSTICS_FILE = previousPath;
		await rm(root, { recursive: true, force: true });
	}
});
