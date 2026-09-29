import { mkdir, open } from "node:fs/promises";
import { dirname } from "node:path";

const CODEX_API = "openai-codex-responses";
const TRANSPORT_FAILURE = "provider_transport_failure";

type UnknownRecord = Record<string, unknown>;

export type CodexTransportFailure = {
	timestamp?: number;
	error?: {
		name?: string;
		message: string;
		code?: string | number;
		stack?: string;
	};
	details?: {
		configuredTransport?: string;
		fallbackTransport?: string;
		eventsEmitted?: boolean;
		phase?: string;
		requestBytes?: number;
	};
};

export type CodexDiagnosticRecord = {
	schemaVersion: 1;
	kind: "websocket_transport_failure" | "codex_provider_error";
	recordedAt: string;
	recordedAtMs: number;
	sessionId: string;
	sessionFile?: string;
	messageTimestamp?: number;
	provider?: string;
	model?: string;
	stopReason?: string;
	errorMessage?: string;
	transportFailures: CodexTransportFailure[];
};

export type AssistantMessageLike = {
	role?: unknown;
	api?: unknown;
	provider?: unknown;
	model?: unknown;
	content?: unknown;
	timestamp?: unknown;
	stopReason?: unknown;
	errorMessage?: unknown;
	diagnostics?: unknown;
};

function isRecord(value: unknown): value is UnknownRecord {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | undefined {
	return typeof value === "string" ? value : undefined;
}

function optionalNumber(value: unknown): number | undefined {
	return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function sanitizeTransportFailure(value: unknown): CodexTransportFailure | undefined {
	if (!isRecord(value) || value.type !== TRANSPORT_FAILURE) return undefined;

	const sourceError = isRecord(value.error) ? value.error : undefined;
	const errorMessage = optionalString(sourceError?.message);
	const sourceDetails = isRecord(value.details) ? value.details : undefined;
	const code = sourceError?.code;

	return {
		timestamp: optionalNumber(value.timestamp),
		error: errorMessage === undefined ? undefined : {
			name: optionalString(sourceError?.name),
			message: errorMessage,
			code: typeof code === "string" || typeof code === "number" ? code : undefined,
			stack: optionalString(sourceError?.stack),
		},
		details: sourceDetails === undefined ? undefined : {
			configuredTransport: optionalString(sourceDetails.configuredTransport),
			fallbackTransport: optionalString(sourceDetails.fallbackTransport),
			eventsEmitted: typeof sourceDetails.eventsEmitted === "boolean" ? sourceDetails.eventsEmitted : undefined,
			phase: optionalString(sourceDetails.phase),
			requestBytes: optionalNumber(sourceDetails.requestBytes),
		},
	};
}

export function createCodexDiagnosticRecord(
	message: AssistantMessageLike,
	context: { sessionId: string; sessionFile?: string; now?: number },
): CodexDiagnosticRecord | undefined {
	if (message.role !== "assistant" || message.api !== CODEX_API) return undefined;

	const diagnostics = Array.isArray(message.diagnostics) ? message.diagnostics : [];
	const transportFailures = diagnostics
		.map(sanitizeTransportFailure)
		.filter((failure): failure is CodexTransportFailure => failure !== undefined);
	const stopReason = optionalString(message.stopReason);
	if (transportFailures.length === 0 && stopReason !== "error") return undefined;

	const now = context.now ?? Date.now();
	return {
		schemaVersion: 1,
		kind: transportFailures.length > 0 ? "websocket_transport_failure" : "codex_provider_error",
		recordedAt: new Date(now).toISOString(),
		recordedAtMs: now,
		sessionId: context.sessionId,
		sessionFile: context.sessionFile,
		messageTimestamp: optionalNumber(message.timestamp),
		provider: optionalString(message.provider),
		model: optionalString(message.model),
		stopReason,
		errorMessage: optionalString(message.errorMessage),
		transportFailures,
	};
}

export async function appendCodexDiagnosticRecord(path: string, record: CodexDiagnosticRecord): Promise<void> {
	await mkdir(dirname(path), { recursive: true, mode: 0o700 });
	const file = await open(path, "a", 0o600);
	try {
		await file.chmod(0o600);
		await file.appendFile(`${JSON.stringify(record)}\n`, "utf8");
	} finally {
		await file.close();
	}
}

export function formatTransportFailure(record: CodexDiagnosticRecord): string | undefined {
	const failure = record.transportFailures.at(-1);
	if (!failure) return undefined;
	const error = failure.error?.message ?? "unknown WebSocket transport error";
	const phase = failure.details?.phase === "before_message_stream_start"
		? "before stream"
		: failure.details?.phase === "after_message_stream_start"
			? "during stream"
			: failure.details?.phase;
	const fallback = failure.details?.fallbackTransport === "sse" ? "fallback: SSE" : undefined;
	return [error, phase, fallback].filter(Boolean).join("; ");
}
