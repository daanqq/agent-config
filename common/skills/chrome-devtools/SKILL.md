---
name: chrome-devtools
description: Uses Chrome DevTools via MCP for efficient debugging, troubleshooting and browser automation. Use when debugging web pages, automating browser interactions, analyzing performance, or inspecting network requests. This skill does not apply to `--slim` mode (MCP configuration).
---

## Core Concepts

**Browser lifecycle**: Browser starts automatically on first tool call using a persistent Chrome profile. Configure via CLI args in the MCP server configuration: `npx chrome-devtools-mcp@latest --help`.
Addional tooling can be enabled by providing the following flags:

- For extension tooling, use the `--categoryExtensions` flag.
- For memory tooling, use the `--memoryDebugging` flag.

**Page targeting**: Page-scoped tools require a `pageId` parameter to target a specific page. Use `list_pages` to see available pages and their IDs (e.g. `pageId: 1`), or use the ID returned when creating a page with `new_page`.
Note: For `evaluate_script`, `pageId` is required when targeting pages. However, when `--categoryExtensions` is enabled, `pageId` is optional so you can pass `serviceWorkerId` instead to evaluate inside an extension background service worker.
**Element interaction**: Use `take_snapshot` to get page structure with element `uid`s. Each element has a unique `uid` for interaction. If an element isn't found, take a fresh snapshot - the element may have been removed or the page changed.

## Workflow Patterns

### Before interacting with a page

1. Navigate: `navigate_page` or `new_page`
2. Wait: `wait_for` to ensure content is loaded if you know what you look for.
3. Snapshot: `take_snapshot` with `pageId` to understand page structure
4. Interact: Use element `uid`s from snapshot for `click`, `fill`, etc., passing the corresponding `pageId`.

### Logging in

When a page requires a login and the project has no login script, request the credentials with the T3 `request_secret` tool (`delivery: "file"`, one call each for login and password). Fill the form with a script that reads those files, delete any generated script afterwards, and never echo the values. Do not ask the user to log in by hand.

### Taking screenshots

`take_screenshot` of a page that is not in the foreground hangs until `Page.captureScreenshot timed out` (about 3 minutes). Before a screenshot of a page you opened with `new_page`, or after working in another page, call `select_page` with that `pageId` and `bringToFront: true`. If a screenshot still times out, bring the page to the front before retrying; never repeat the same call as is.

### Connecting to the user's own browser

When the user asks you to look at their browser (a reproduction in their tabs, their session), the MCP server of this session cannot help: it runs with `--headless --isolated` and sees only its own empty Chrome. Do not change the MCP configuration. Instead:

1. Ask the user not to reload or clear the reproducing tab, then to open `chrome://inspect/#remote-debugging` in the same Chrome and enable remote debugging. `~/.config/google-chrome/DevToolsActivePort` appears when it is on.
2. Attach the CLI of the same package: `C="npx -y -p chrome-devtools-mcp@latest chrome-devtools"; $C start --autoConnect --no-usage-statistics`, then `$C list_pages`. Chrome may ask the user to allow the connection. Every MCP tool is a CLI command with the same arguments (`$C <tool> --help`); run each under `timeout`.
3. Only read until the user allows changes such as reloading. Run `$C stop` when you are done.

### Efficient data retrieval

- Use `filePath` parameter for large outputs (screenshots, snapshots, traces)
- Use pagination (`pageIdx`, `pageSize`) and filtering (`types`) to minimize data
- Set `includeSnapshot: false` on input actions unless you need updated page state

### Tool selection

- **Automation/interaction**: `take_snapshot` (text-based, faster, better for automation)
- **Visual inspection**: `take_screenshot` (when user needs to see visual state)
- **Additional details**: `evaluate_script` for data not in accessibility tree

### Parallel execution

You can send multiple tool calls in parallel, but maintain correct order: navigate → wait → snapshot → interact.

### Testing an extension

> **Before proceeding**: Extension tools (`install_extension`, `list_extensions`, etc.) are only available when the MCP server is started with the `--categoryExtensions` flag. If these tools are not in your tool list, stop and ask the user to update their MCP server configuration:
>
> ```json
> {
>   "mcpServers": {
>     "chrome-devtools": {
>       "command": "npx",
>       "args": ["chrome-devtools-mcp@latest", "--categoryExtensions"]
>     }
>   }
> }
> ```
>
> After updating, the user must restart the MCP server (or their AI client) for the change to take effect.

1. **Install**: Use `install_extension` with the path to the unpacked extension.
2. **Identify**: Get the extension ID from the response or by calling `list_extensions`.
3. **Trigger Action**: Use `trigger_extension_action` to open the popup or side panel if applicable.
4. **Verify Service Worker**: Use `evaluate_script` with `serviceWorkerId` (omitting `pageId` and `args`) to check extension state or trigger background actions. When evaluating in a page, pass `pageId` (omitting `serviceWorkerId`).
5. **Verify Page Behavior**: Navigate to a page where the extension operates and use `take_snapshot` to check if content scripts injected elements or modified the page correctly.

## Troubleshooting

If `chrome-devtools-mcp` is insufficient, guide users to use Chrome DevTools UI:

- https://developer.chrome.com/docs/devtools
- https://developer.chrome.com/docs/devtools/ai-assistance

If there are errors launching `chrome-devtools-mcp` or Chrome, refer to https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/troubleshooting.md.
