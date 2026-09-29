---
name: eutp-worktree
description: Prepare a dedicated git worktree for an EUTP implementation when the user requests isolation, the original checkout has pre-existing or unrelated changes, multiple repositories need independent changes, or the task explicitly requires a worktree.
---

# EUTP worktree

Use this skill only after deciding that repository isolation is needed. Do not
create a worktree solely because the task has an EUTP ID.

If the original checkout is clean, only one repository is affected, and the user
did not request isolation, implement in the original checkout on the task branch.
If work for the same ticket was already transferred from a worktree, continue in
that original checkout and do not create another worktree for the same task.

When isolation is required, create a dedicated worktree from master/main/another
base branch under `~/echat/worktrees/`, unless the user specifies another location.

Name it `<repository>-EUTP-<digits>`, using the repository name and ticket ID.
For example, for 'tidy-client' repo:

```text
~/echat/worktrees/tidy-client-EUTP-123123
```

Create one worktree per affected repository.
Make new branch named 'task/EUTP-123123' if task needs one repo changes,
or 'feature/EUTP-123123' if multiple repos. Reuse an existing matching worktree after verifying
that it belongs to the same ticket and repository; do not overwrite or remove it.

Before implementation checks, install the dependencies declared by the existing
lockfile in every affected worktree if its dependency directory is missing or
incomplete. This is allowed and expected: it is not adding a dependency and
must not modify package manifests or lockfiles.

Do not skip requested checks because dependencies are absent. If dependency
installation fails, report the exact command and blocker before declaring the
implementation complete.

Perform the requested implementation and its checks from the worktree.
