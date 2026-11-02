---
name: analyze-spacehub-task
description: Analyze an ESOFT SpaceHub task against the codebase, read-only. Use for analysis or planning requests containing a T-ID or SpaceHub task URL, when user asks to analyze task and gives you task URL.
---

# Analyze SpaceHub Task

Unless the user explicitly requests implementation, keep the work read-only.

Get the task context with [`fetch-spacehub-task`](../fetch-spacehub-task/SKILL.md)
through the active agent's SpaceHub MCP tools. Follow its rules for exact task
lookup, programming works, linked tasks, attachments, and refetching. Analyze
the requested task's description, artifacts, and metadata together with its
programming works; when they disagree, the programming work wins for
implementation and the disagreement is reported.
Before writing conclusions, apply the checks in
[`references/analysis-checks.md`](references/analysis-checks.md) whose condition
matches the task, such as spatial claims from screenshots or video.

After the task context is written, resolve this skill's directory as
`SKILL_ROOT` and label the calling Herdr tab with the task ID and title:

```sh
python3 "$SKILL_ROOT/scripts/rename-herdr-tab.py" <context_dir>/task.json
```

Renaming the tab does not change the repository and is allowed in read-only
work. The script skips outside Herdr and only warns on failure; continue the
analysis either way.

Completion criterion: the target issue, its programming works, and relevant
accessible attachments have been analyzed without other unrequested
related-issue fetches.

If the user requests implementation, first decide with
[`task-worktree`](../task-worktree/SKILL.md) whether a worktree is allowed and
needed: it owns the repositories that allow worktrees and the isolation
conditions. Without a worktree, implement in the original checkout on the task
branch. Follow the branch contract in `task-worktree` even without a worktree;
it owns the default feature branch and the gate for decomposed task branches.

If work for the same ticket was already transferred from a worktree, inspect the
original checkout and continue there on its established task branch. Do not create
another worktree merely because the checkout contains the already-transferred
changes.
