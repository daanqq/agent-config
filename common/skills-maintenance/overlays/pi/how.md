# `how` semantic overlay

## Preserve

- Keep automatic invocation and the Pi-facing distinction between runtime mechanics (`how`) and historical rationale (`why`).
- Build the explanation from code, callers, state transitions, boundaries, and focused checks; distinguish observed facts from inference.
- Respect read-only task mode and the active `AGENTS.md` delegation limits.
- Retain the local critic workflow and files `references/critic-prompt.md`, `references/critique-rubric.md`, and `references/explorer-prompt.md`.
- Preserve the bundled license and Pi metadata.

## Replace or omit from upstream

- Do not depend on Cursor-only orchestration, MCP connectors, or unavailable skills.
- Keep architecture criticism separate from the factual explanation and run it only when the request includes critique or the architecture question requires it.
- Omit upstream reference files that only support the removed Cursor orchestration path.

## Acceptance

The answer should give a senior engineer a usable mental model, cite concrete code, explain ownership and data flow, and state any uncertainty or unavailable runtime evidence.
