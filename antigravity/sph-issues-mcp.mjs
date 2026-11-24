#!/usr/bin/env node
// Stdio-to-Streamable-HTTP bridge for SpaceHub issues MCP.
// Antigravity mcp_config.json does not expand ${ENV_VAR} in HTTP headers,
// so this bridge reads SPACEHUB_MCP_TOKEN at runtime and keeps secrets out of git.

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";

const MCP_URL =
  process.env.SPACEHUB_MCP_URL || "https://spacehub.esoft.tech/api/user-mcp/sph/v1/issues";
const ENV_FALLBACK_FILE = join(homedir(), ".config", "spacehub-inbox", "env");
const REQUEST_TIMEOUT_MS = 60_000;

function readTokenFromEnvFile(filePath) {
  try {
    const content = readFileSync(filePath, "utf8");
    for (const rawLine of content.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      const cleaned = line.startsWith("export ") ? line.slice(7).trim() : line;
      const eq = cleaned.indexOf("=");
      if (eq < 0) continue;
      const key = cleaned.slice(0, eq).trim();
      if (key !== "SPACEHUB_MCP_TOKEN") continue;
      let val = cleaned.slice(eq + 1).trim();
      if (
        (val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))
      ) {
        val = val.slice(1, -1);
      }
      if (val) return val;
    }
  } catch {
    return "";
  }
  return "";
}

function resolveToken() {
  const fromEnv = process.env.SPACEHUB_MCP_TOKEN?.trim();
  if (fromEnv) return fromEnv;
  return readTokenFromEnvFile(ENV_FALLBACK_FILE);
}

function writeJsonLine(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function parseSsePayloads(body) {
  const payloads = [];
  for (const event of body.split(/\r?\n\r?\n/)) {
    const dataLines = [];
    for (const line of event.split(/\r?\n/)) {
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    const data = dataLines.join("\n").trim();
    if (!data || data === "[DONE]") continue;
    payloads.push(JSON.parse(data));
  }
  return payloads;
}

let sessionId = null;

async function forwardMessage(rawLine) {
  let message;
  try {
    message = JSON.parse(rawLine);
  } catch (error) {
    process.stderr.write(`sph-issues-mcp: invalid JSON input: ${error.message}\n`);
    return;
  }

  const hasId = message && typeof message === "object" && Object.hasOwn(message, "id");
  const token = resolveToken();
  if (!token) {
    if (hasId) {
      writeJsonLine({
        jsonrpc: "2.0",
        id: message.id,
        error: {
          code: -32001,
          message:
            "SPACEHUB_MCP_TOKEN is not set in environment or ~/.config/spacehub-inbox/env",
        },
      });
    }
    return;
  }

  const headers = {
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    authorization: `Bearer ${token}`,
  };
  if (sessionId) {
    headers["mcp-session-id"] = sessionId;
  }

  let res;
  let text;
  try {
    res = await fetch(MCP_URL, {
      method: "POST",
      headers,
      body: JSON.stringify(message),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    const nextSessionId = res.headers.get("mcp-session-id");
    if (nextSessionId) sessionId = nextSessionId;
    text = await res.text();
  } catch (error) {
    if (hasId) {
      writeJsonLine({
        jsonrpc: "2.0",
        id: message.id,
        error: {
          code: -32000,
          message: `SpaceHub MCP request failed: ${error.message}`,
        },
      });
    }
    return;
  }

  if (res.status === 202 || !text.trim()) {
    return;
  }

  if (!res.ok) {
    if (hasId) {
      writeJsonLine({
        jsonrpc: "2.0",
        id: message.id,
        error: {
          code: -32000,
          message: `SpaceHub MCP HTTP ${res.status}: ${text.slice(0, 300)}`,
        },
      });
    }
    return;
  }

  try {
    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("text/event-stream")) {
      for (const payload of parseSsePayloads(text)) {
        writeJsonLine(payload);
      }
    } else {
      writeJsonLine(JSON.parse(text));
    }
  } catch (error) {
    if (hasId) {
      writeJsonLine({
        jsonrpc: "2.0",
        id: message.id,
        error: {
          code: -32000,
          message: `SpaceHub MCP invalid response: ${error.message}`,
        },
      });
    }
  }
}

const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
let chain = Promise.resolve();

rl.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  chain = chain.then(() => forwardMessage(trimmed));
});

rl.on("close", () => {
  chain.finally(() => process.exit(0));
});
