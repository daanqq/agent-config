---
name: task-worktree
description: Branch naming (`feature/T-`, `task/T-`) and isolated Git worktrees for SpaceHub tasks. Use before creating any task branch, or when the user requests isolation, existing unrelated changes require it, or several repositories need independent changes.
---

# Task Worktree

Follow the branch contract for every new task branch. Create a worktree only
when repository isolation is needed and the repository allows worktrees: a task
ID alone does not require one. Judge the checkout from a fresh `git status` and
current branch, not from earlier observations.

Worktrees are allowed only in these repositories under `~/echat/`:

- `tidy-client`: code, tests, and browser checks; `echat-browser-check` serves a
  worktree through `worktree-client.sh`.
- `tidy-rest`, `tidy-server`, `tidy-proto`: code, tests, and builds. Their stands
  run only from the original checkout, so a stand or browser check first needs
  the changes moved back with
  [`task-worktree-transfer`](../task-worktree-transfer/SKILL.md).

Every other repository, including the Space services under
`~/deploy/env/development/services/`, works in its original checkout: their
stands build only from it, so a worktree cannot be checked. If that checkout has
unrelated changes, is on another branch, or serves a stand, ask the user once
whether to switch it to the task branch (the stand then serves the task); do not
create a worktree instead.

In an allowed repository, if the checkout is clean, only one repository is
affected, isolation was not requested, and the original checkout is on its base
branch and serves no stand, use it for the task branch. Isolation is required
when the checkout is on another branch (another task's work may be running from
it), or when a stand runs from it: `devtask status` lists it, or a tmux session
such as `echat-client` serves that path. Switching branches there silently
changes the code the stand serves. If the same task was already transferred
back, continue in that checkout.

## Branch contract

- The prefix follows the MR target. A branch whose MR targets the integration
  branch (master/main) is always `feature/T-<task-id>`, whatever the task class
  (bug or feature) and repository count. `task/T-<task-id>` merges only into its
  parent `feature/`. Existing `task/` branches merged into master are legacy,
  not a naming precedent. New branch names always use task T-IDs, never work J-IDs.
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
- Several repositories may use the same feature T-ID; that is not decomposition.
- A hotfix branch is still `feature/T-<task-id>`, created from the latest
  `release-*` branch with `git switch --no-track -c feature/T-<task-id> origin/release-<version>`:
  without `--no-track` a plain push goes to the release branch. Its MR targets
  `hotfix/<version>`; until the user prepares that branch, target the release branch.

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
