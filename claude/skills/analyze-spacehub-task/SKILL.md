---
name: analyze-spacehub-task
description: Analyze an ESOFT SpaceHub task against the codebase, read-only. Use for analysis or planning requests containing a T-ID or SpaceHub task URL.
---

# Analyze SpaceHub Task

Unless the user explicitly requests implementation, keep the work read-only.

Get the task context with [`fetch-spacehub-task`](../fetch-spacehub-task/SKILL.md)
through the active agent's SpaceHub MCP tools. Follow its rules for exact task
lookup, artifacts, linked tasks, and attachments. Analyze only the requested
task's description, artifacts, and metadata.

Completion criterion: the target issue and relevant accessible attachments
have been analyzed without unrequested related-issue fetches.

If the user requests implementation, first decide whether repository isolation is needed.
Use [`task-worktree`](../task-worktree/SKILL.md) only when the user requests a worktree, the original
checkout contains pre-existing or unrelated changes, multiple repositories need
independent changes, or the task explicitly requires isolation. If the original
checkout is clean and only one repository is affected, implement in the original
checkout on the task branch. Follow the branch contract in `task-worktree`
even without a worktree; it owns the default feature branch and the gate for
decomposed task branches.

If work for the same ticket was already transferred from a worktree, inspect the
original checkout and continue there on its established task branch. Do not create
another worktree merely because the checkout contains the already-transferred
changes.
