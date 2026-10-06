---
name: task-worktree
description: Prepare an isolated Git worktree for a SpaceHub task when the user requests isolation, existing unrelated changes require it, or several repositories need independent changes.
---

# Task Worktree

Use this skill only when repository isolation is needed. A task ID alone does
not require a worktree. If the checkout is clean, only one repository is affected,
and isolation was not requested, use the original checkout on the task branch.
If the same task was already transferred back, continue in that checkout.

## Branch contract

- Ordinary implementation uses `feature/T-<task-id>` regardless of repository
  count. New branch names always use task T-IDs, never work J-IDs.
- Use `task/T-<child-task-id>` only when the user explicitly requests splitting
  one feature into several task branches AND the parent SpaceHub task contains
  more than one programming work. Check that condition with
  [`fetch-spacehub-task`](../fetch-spacehub-task/SKILL.md); multiple works alone
  do not authorize decomposition. The MCP `create_work` description currently
  limits a native task to one programming work and models an aggregating feature
  through nested tasks. If the fetched structure cannot satisfy the agreed gate,
  keep the ordinary feature branch and ask the user to clarify decomposition;
  do not silently count nested tasks or non-programming works as programming works.
- Every child has an established T-ID and a named parent `feature/T-<parent-id>`.
  Create its branch from that parent and target its MR to that parent, not to
  master/main. Do not invent child T-IDs or derive them from J-ID numbers.
  If the child IDs or parent relationship are missing, ask before creating
  branches. Do not create SpaceHub tasks or works without a separate request.
- The parent feature MR targets the repository's normal integration branch.
  Several repositories may use the same feature T-ID; that is not decomposition.

When isolation is required, create one worktree per affected repository under
`~/echat/worktrees/` unless the user specifies another location. Name it
`<repository>-T-<task-id>`, for example `tidy-client-T-123123`. Ordinary feature
worktrees start from the agreed integration base; decomposed task worktrees
start from their parent feature branch.

Reuse a matching established branch/worktree only after verifying repository,
task identity, and intended target. Do not rename historical branches, overwrite
user changes, or remove an existing worktree just to enforce new naming.

Before implementation checks, install dependencies declared by the existing
lockfile when missing or incomplete. Do not modify package manifests/lockfiles.
Run the requested implementation and checks in the selected checkout. Report
installation/check failures before declaring completion.
