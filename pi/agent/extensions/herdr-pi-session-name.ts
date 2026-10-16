// Reports the pi session name to herdr as the `pi_session` pane metadata token,
// so herdr sidebar rows can show it as `$pi_session`. Kept beside the
// herdr-managed herdr-agent-state.ts, which reinstalling the integration overwrites.

import net from "node:net";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const source = "herdr:pi-session-name";
const socketPath = process.env.HERDR_SOCKET_PATH;
const socketEndpoint =
  process.platform === "win32" && socketPath ? `\\\\.\\pipe\\${socketPath}` : socketPath;
const paneId = process.env.HERDR_PANE_ID;

function enabled(): boolean {
  return process.env.HERDR_ENV === "1" && !!socketPath && !!paneId;
}

function sendRequestAttempt(request: unknown, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    let done = false;
    const socket = net.createConnection(socketEndpoint!);
    const finish = (delivered: boolean) => {
      if (done) return;
      done = true;
      clearTimeout(timeout);
      socket.destroy();
      resolve(delivered);
    };
    socket.on("error", () => finish(false));
    socket.on("connect", () => socket.write(`${JSON.stringify(request)}\n`));
    socket.on("data", () => finish(true));
    socket.on("end", () => finish(false));
    const timeout = setTimeout(() => finish(false), timeoutMs);
    timeout.unref?.();
  });
}

// herdr drops reports whose seq is not newer than the last one for this source,
// so seed from the clock to stay ahead of reports from a previous pi process.
let reportSeq = Date.now() * 1000;

async function reportSessionName(name: string | undefined): Promise<void> {
  if (!enabled()) return;
  reportSeq += 1;
  const request = {
    id: `${source}:${Date.now()}:${Math.random().toString(36).slice(2)}`,
    method: "pane.report_metadata",
    params: {
      pane_id: paneId,
      source,
      seq: reportSeq,
      tokens: { pi_session: name ?? null },
    },
  };
  if (await sendRequestAttempt(request, 500)) return;
  await sendRequestAttempt(request, 1500);
}

export default function herdrPiSessionNameExtension(pi: ExtensionAPI) {
  let rootSession = false;

  pi.on("session_start", async (_event, ctx) => {
    // Only the interactive TUI session owns the herdr pane; headless modes do not.
    if (ctx?.mode !== "tui") return;
    rootSession = true;
    await reportSessionName(pi.getSessionName());
  });

  pi.on("session_info_changed", (event) => {
    if (!rootSession) return;
    void reportSessionName(event?.name);
  });
}
