import { rm } from "node:fs/promises";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function sessionDeleteExtension(pi: ExtensionAPI) {
  pi.registerCommand("delete", {
    description: "Delete the current session after confirmation",
    handler: async (_args, ctx) => {
      await ctx.waitForIdle();

      const sessionFile = ctx.sessionManager.getSessionFile();
      if (!sessionFile) {
        ctx.ui.notify("Current session is not persisted", "warning");
        return;
      }

      const confirmed = await ctx.ui.confirm(
        "Delete current session?",
        "This will start a new session and remove the current one from history.",
      );
      if (!confirmed) return;

      const result = await ctx.newSession({
        withSession: async (newCtx) => {
          newCtx.ui.notify("Started a new session", "info");
        },
      });
      if (result.cancelled) return;

      await rm(sessionFile, { force: true });
    },
  });
}
