# `chrome-devtools` semantic overlay

## Preserve

- Keep the upstream content of `chrome-devtools-mcp` `skills/chrome-devtools` unchanged, including automatic invocation and the `--slim` exclusion.
- Keep the local login rule under "Logging in" in `SKILL.md`: when a page requires a login and the project has no login script, request credentials with the T3 `request_secret` tool (`delivery: "file"`), fill the form from a script that reads the files, never echo the values, and never ask the user to log in by hand.
- Keep the local "Connecting to the user's own browser" section in `SKILL.md`: the isolated MCP server cannot see the user's Chrome; ask to enable `chrome://inspect/#remote-debugging`, attach with `npx -y -p chrome-devtools-mcp@latest chrome-devtools start --autoConnect`, read only until allowed, and stop the CLI afterwards.
- Keep the local `pageId` line right after **Page targeting** in `SKILL.md`: take `pageId` only from the latest `new_page` or `list_pages` response, do not send `new_page` in the same message as calls that need its `pageId`, and call `list_pages` after "No page found" before retrying.
- Keep the local "Specialized workflows" section before **Troubleshooting**: it routes to `cookie-debugging`, `debug-optimize-lcp`, `memory-leak-debugging` and `a11y-debugging`, which Claude Code hides from automatic selection through `skillOverrides`.
- Keep the local "Taking screenshots" section in `SKILL.md`: before `take_screenshot` of a page that may be in the background, call `select_page` with `bringToFront: true`; after `Page.captureScreenshot timed out`, bring the page to the front instead of repeating the call.

## Replace or omit from upstream

- Nothing is removed from upstream; the `pageId`, login, screenshot, own-browser and specialized-workflow rules are the only additions.

## Acceptance

After an upstream update the `pageId` line under **Page targeting** and the "Logging in", "Taking screenshots" and "Connecting to the user's own browser" and "Specialized workflows" sections are still present, and the rest of the skill matches upstream.
