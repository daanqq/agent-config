---
name: spacehub-write
description: Use before any write to ESOFT SpaceHub through MCP - creating tasks or works, comments, tags, artifacts. Reading is `fetch-spacehub-task`.
compatibility: Requires an authenticated SpaceHub issues MCP server in the active agent. Works in Pi and Claude Code.
---

# SpaceHub write

A write is an external action visible to colleagues. Make it only on the user's
explicit instruction or under a grant from the invoking workflow (`task-to-mr`
grants the `Merge requests` artifact). Without either, ask first.

Tools are `mcp__sph-issues__<tool>` in Claude Code and `mcp__sph_issues__<tool>`
in Pi. Write tools: `create_task`, `create_work`, `create_artifact`,
`update_artifact`, `add_issue_comment`, `add_issue_tag`. Reading and
`list_artifact_templates` are not writes. If the server is unavailable or
unauthenticated, report the blocker; do not fall back to raw HTTP or the UI.

## Rules

- **Epic.** `create_task` requires `epic_id`. For EChat choose it from the table
  in `~/echat/AGENTS.md`, section «Оформление задач в SpaceHub» → «Выбор эпика».
- **Works.** `create_work` limits works per task; see the constraints in
  [`task-worktree`](../task-worktree/SKILL.md).
- **Status.** No tool changes the state of an existing task or work. Set `state`
  deliberately in `create_task` / `create_work` (omitted, a task is a draft), and
  tell the user which state changes remain for them.
- **Sprint.** `create_work` without `sprint` uses the current sprint and failed
  with `Sprint dateStart ... should have timezone info`. Pass `sprint: "none"`
  (the work is then created without a sprint) and tell the user.
- **Comments.** `add_issue_comment` takes `issue_id`, `text`, optional `author`;
  the server adds an AI-agent signature. It failed with `visibility Field
  required` although the schema has no `visibility` parameter, and no workaround
  is known. On that error do not retry; give the user the comment text.
- **`Merge requests` artifact.** It holds only MR URLs, one per line, no
  captions. Read the task with `get_issue`, then call `update_artifact` with the
  full text: the existing lines plus each missing URL. Without that artifact,
  `create_artifact` with title exactly `Merge requests` and no template.

## Verify

After each write, call `get_issue` for the task and confirm the result is there
(state, artifact text, comment); report what you could not confirm.
