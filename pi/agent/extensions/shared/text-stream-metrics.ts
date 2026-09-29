export type TextStreamMetrics = {
	ttftMs?: number;
	tps?: number;
};

export function calculateTextStreamMetrics(input: {
	outputTokens: number;
	reasoningTokens?: number;
	requestStartedAt?: number;
	firstTextDeltaAt?: number;
	lastTextDeltaAt?: number;
	hasToolCalls: boolean;
}): TextStreamMetrics | undefined {
	const { firstTextDeltaAt, lastTextDeltaAt, requestStartedAt } = input;
	if (firstTextDeltaAt === undefined) return undefined;

	const metrics: TextStreamMetrics = {};
	if (requestStartedAt !== undefined && firstTextDeltaAt >= requestStartedAt) {
		metrics.ttftMs = firstTextDeltaAt - requestStartedAt;
	}

	const visibleOutputTokens = Math.max(0, input.outputTokens - (input.reasoningTokens ?? 0));
	if (!input.hasToolCalls && lastTextDeltaAt !== undefined && lastTextDeltaAt > firstTextDeltaAt && visibleOutputTokens > 0) {
		metrics.tps = Math.round(visibleOutputTokens / ((lastTextDeltaAt - firstTextDeltaAt) / 1000));
	}

	return metrics;
}
