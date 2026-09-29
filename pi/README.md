![pi-config screenshot](https://iili.io/nnqm374.png)
# pi-config

Personal configuration for the `pi` coding agent.

## Usage requirements

- Running CLIProxy at http://127.0.0.1:8317

## Extensions

| Extension | Description | Commands |
| --- | --- | --- |
| `00-ui-00-transition.ts` | Buffers terminal output during TUI session transitions until resources are ready. | — |
| `00-ui-editor.ts` | Custom input editor and skill autocomplete. | — |
| `00-ui-footer.ts` | Compact two-line status footer. | — |
| `00-ui-header.ts` | Theme-aware gradient header. | — |
| `agent-pulse.ts` | Agent activity and elapsed-time indicator. | — |
| `apply-patch/` | Adds the Codex-style `apply_patch` tool. | — |
| `auto-session-name/` | Names new sessions in English after the first completed response; uses `New session` if generation fails. | — |
| `balance.ts` | Shows DeepSeek and OpenRouter balances. | `/deepseek:balance`, `/openrouter:balance` |
| `cliproxy-quota/` | Shows combined and per-account Codex quotas through CLIProxyAPI. | `/cliproxy:quota`, `/statuses` |
| `context-limit-warning.ts` | Warns when context exceeds 128k tokens. | — |
| `fullscreen-scroll-speed.ts` | Makes fullscreen wheel scrolling five times faster; Alt keeps Pi's additional five-times multiplier. | — |
| `herdr-agent-state.ts` | Reports Pi session and agent state to Herdr. | — |
| `mr-echat.ts` | Commits, pushes, and creates EChat merge requests. | `/mr-echat [--name=<ветка>]` |
| `pi-paste.ts` | Restores long pasted text after a repeated paste. | — |
| `session-delete.ts` | Deletes the current session safely. | `/delete` |
| `shake.ts` | Removes bulky content from session context. | `/shake` |
| `skill-dollar.ts` | Expands `$skill-name` references. | `$<skill-name>` |
| `subagents/` | Runs background agents. | `/subagents`, `/btw` |
| `system-info.ts` | Adds runtime system information to the agent system prompt. | — |
| `token-efficiency.ts` | Records per-request usage, estimated context sources, active tool loadout, and tool errors outside the model context. | — |
| `zsh.ts` | Runs user shell commands through zsh. | — |

## Local commands

| Command | Purpose |
| --- | --- |
| `make dep` | Installs all dependencies for the local extension packages. |
