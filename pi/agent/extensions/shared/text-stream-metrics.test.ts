import assert from "node:assert/strict";
import { test } from "node:test";
import { calculateTextStreamMetrics } from "./text-stream-metrics.ts";

test("separates time to first token from text streaming throughput", () => {
	assert.deepEqual(calculateTextStreamMetrics({
		outputTokens: 820,
		reasoningTokens: 100,
		requestStartedAt: 1_000,
		firstTextDeltaAt: 5_000,
		lastTextDeltaAt: 15_000,
		hasToolCalls: false,
	}), {
		ttftMs: 4_000,
		tps: 72,
	});
});

test("does not report text TPS when output token usage also contains tool calls", () => {
	assert.deepEqual(calculateTextStreamMetrics({
		outputTokens: 200,
		requestStartedAt: 1_000,
		firstTextDeltaAt: 2_000,
		lastTextDeltaAt: 4_000,
		hasToolCalls: true,
	}), {
		ttftMs: 1_000,
	});
});

test("does not reuse metrics when an assistant message has no text stream", () => {
	assert.equal(calculateTextStreamMetrics({
		outputTokens: 100,
		requestStartedAt: 1_000,
		hasToolCalls: true,
	}), undefined);
});
