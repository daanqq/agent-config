import assert from "node:assert/strict";
import test from "node:test";
import { formatReasoningEffort } from "./src/format.ts";
import { buildSubagentSpawnResult } from "./src/prompt.ts";

test("reasoning effort formatting distinguishes an effective level from a backend default", () => {
  assert.equal(formatReasoningEffort("high"), "reasoning: high");
  assert.equal(formatReasoningEffort(undefined), "reasoning: default");
});

test("spawn result shows reasoning effort beside the model", () => {
  assert.match(
    buildSubagentSpawnResult({
      id: "sa-1",
      title: "test",
      harness: "pi",
      modelLabel: "openai-codex/gpt-5.6-luna",
      reasoningEffort: "high",
      cwd: "/tmp/project",
    }),
    /\(pi: openai-codex\/gpt-5\.6-luna, reasoning: high, \/tmp\/project\)/,
  );
});
