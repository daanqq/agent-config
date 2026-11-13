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
Where the tools are deferred, load a tool's schema before its first call:
argument names are not guessable (`update_artifact` takes `artifact_id`, not
`artifact_sid`).

## Rules

- **Epic.** `create_task` requires `epic_id`. For EChat choose it from the table
  in `~/echat/AGENTS.md`, section «Оформление задач в SpaceHub» → «Выбор эпика».
- **Works.** `create_work` limits works per task; see the constraints in
  [`task-worktree`](../task-worktree/SKILL.md).
- **Status.** No tool changes the state of an existing task or work. Set `state`
  deliberately in `create_task` / `create_work` (omitted, a task is a draft), and
  tell the user which state changes remain for them.
- **Programming work.** A task created to be implemented (the user asks to
  implement it, or `task-to-mr` runs on it) gets its «Программирование» work in
  the same go: `create_task` with `state: "in-progress"`, then `create_work` with
  `activity: "Программирование"` and `state: "in-progress"`. A programming work
  added later to an existing task also starts `in-progress`, even with its MR
  already open: moving it to review is the user's step.
- **Sprint.** `create_work` without `sprint` uses the current sprint and failed
  with `Sprint dateStart ... should have timezone info`. Pass `sprint: "none"`
  (the work is then created without a sprint) and tell the user.
- **Comments.** `add_issue_comment` takes `issue_id`, `text`, optional `author`;
  the server adds an AI-agent signature. It failed with `visibility Field
  required` although the schema has no `visibility` parameter, and no workaround
  is known. On that error do not retry; give the user the comment text.
- **Result artifacts.** `Что было сделано` and `Merge requests` belong to the
  task's programming work (the J- under `works` with activity «Программирование»);
  write them to the task only when it has no such work. The task's `get_issue`
  also lists its works' artifacts, so read the work with `get_issue <J-ID>` to
  see which of them it owns. Update the work's artifact, or `create_artifact`
  with `issue_id` set to the J-ID, the exact title and no template. Leave a
  same-title artifact of the task itself untouched: a new task gets an empty
  `Что было сделано` from its template.
- **`Merge requests` artifact.** It holds only MR URLs, one per line, no
  captions. `update_artifact` takes the full text: the existing lines plus each
  missing URL.

## Verify

After each write, call `get_issue` for the issue you wrote to (the work for its
artifacts) and confirm the result is there (state, artifact text, comment);
report what you could not confirm.
