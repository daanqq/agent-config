import { readFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const templates = new Map([
  ["gpt-6.2-sol", new URL("./gpt-6.2-sol.md", import.meta.url)],
  ["gpt-6.2-astra", new URL("./gpt-6.2-astra.md", import.meta.url)],
]);

export function withCodexGpt62Instructions(payload: unknown): Record<string, unknown> | undefined {
  if (typeof payload !== "object" || payload === null) return;
  if (!("model" in payload) || typeof payload.model !== "string") return;
  if (!("instructions" in payload) || typeof payload.instructions !== "string") return;

  const template = templates.get(payload.model);
  if (!template) return;

  const instructions = readFileSync(template, "utf8").trim();
  return { ...payload, instructions: `${payload.instructions}\n\n${instructions}` };
}

export default function (pi: ExtensionAPI) {
  pi.on("before_provider_request", ({ payload }, { model }) => {
    if (model?.provider === "openai-codex" && model.api === "openai-codex-responses") {
      return withCodexGpt62Instructions(payload);
    }
  });
}
