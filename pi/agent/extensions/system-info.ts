import os from "node:os";
import process from "node:process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

function safe<T>(fn: () => T): T | undefined {
  try {
    return fn();
  } catch {
    return undefined;
  }
}

function systemInfo() {
  const compact = [
    "Runtime:",
    `- OS: ${os.type()} ${os.release()} (${os.platform()} ${os.arch()})`,
    `- Shell: ${process.env.SHELL ?? process.env.ComSpec ?? "unknown"}`,
  ];
  if (process.env.PI_VERBOSE_SYSTEM_INFO !== "1") return compact.join("\n");

  const user = safe(() => os.userInfo().username) ?? "unknown";
  return [
    ...compact,
    `- Hostname: ${os.hostname()}`,
    `- User: ${user}`,
    `- Home: ${os.homedir()}`,
    `- Node: ${process.version}`,
  ].join("\n");
}

export default function (pi: ExtensionAPI) {
  pi.on("before_agent_start", async (event) => ({
    systemPrompt: `${event.systemPrompt}\n\n${systemInfo()}`,
  }));
}
