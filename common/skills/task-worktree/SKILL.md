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

- `tidy-client`, `tidy-rest`, `tidy-server`: code, tests, and browser checks; a
  task stand of `echat-stand` serves their worktrees. When `echat-browser-check`
  needs the legacy stack instead, it serves a tidy-client worktree through
  `worktree-client.sh`, but runs tidy-rest and tidy-server only from the
  original checkout: a check there first needs the changes moved back with
  [`task-worktree-transfer`](../task-worktree-transfer/SKILL.md).
- `tidy-proto`: code, tests, and builds.

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
it), or when a stand runs from it: `devtask status` or `echat-stand status`
lists it, or a tmux session such as `echat-client` serves that path. Switching
branches there silently changes the code the stand serves. If the same task was already transferred
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

When running inside a T3 Code metarepo worktree of `~/echat` (e.g. `~/.t3/worktrees/echat/<slug>/`, configured via `~/echat/t3.json`), isolation is already provided by T3 for the 8 core repositories (`tidy-client`, `tidy-rest`, `tidy-server`, `tidy-adm`, `tidy-proto`, `miniapp`, `esoft-rn-monorepo`, `echat-desktop-app`). Work directly in `./<repository>` inside that T3 worktree so T3 tracks diffs across all modified repositories in its Changes UI, and rename any auto-generated `t3/...` branch to the contract branch (`feature/T-<task-id>` or `task/T-<child-task-id>`) in each modified child repository before committing or opening an MR; leave the metarepo root itself clean. For repositories excluded from `t3.json` or when running from the root `~/echat` checkout (without a T3 worktree), create one worktree per affected repository under `~/echat/worktrees/` unless the user specifies another location, named `<repository>-T-<task-id>` (for example `tidy-client-T-123123`). Ordinary feature worktrees start from the agreed integration base; decomposed task worktrees start from their parent feature branch. Do not launch a task thread with T3 Code's `workspaceStrategy: "worktree"` from a subproject (such as `tidy-client` or `tidy-rest`): a single-repo worktree under `~/.t3/worktrees/<repo>/` cuts the session and its delegated reviewers off from `~/echat/AGENTS.md`, `~/echat/docs/agent/coding-standards/`, and `~/echat/.agents/skills/`. Launch EChat task threads in the `echat` project (`~/echat`).

Reuse a matching established branch/worktree only after verifying repository,
task identity, and intended target. Do not rename historical branches, overwrite
user changes, or remove an existing worktree just to enforce new naming.

Before implementation checks, install dependencies declared by the existing
lockfile when missing or incomplete. When creating a branch from an advanced
`origin/<base>` in an existing checkout, check whether the lockfile changed
(`! git diff --quiet <old-head>..HEAD -- package-lock.json`) and synchronize
`node_modules` (`npm ci`) before the first test or lint run; never recreate
`node_modules` or `build/` in a checkout that currently serves a running local
stand. Do not modify package manifests/lockfiles.
Run the requested implementation and checks in the selected checkout. Report
installation/check failures before declaring completion.
