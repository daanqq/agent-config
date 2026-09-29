---
name: eutp-worktree-transfer
description: Transfer completed EUTP worktree branches and uncommitted changes back to their original repository checkouts for local builds. Use after EUTP implementation in one or more worktrees when the user asks to move the work to the original repositories.
---

# EUTP worktree transfer

For every affected repository:

1. Identify the task worktree, original checkout, and original task branch. For an MR, use its `source_branch`; otherwise use the established task branch, usually `feature/*` or `task/*`. Do not use a temporary `mr-review-*` branch as the destination. Verify the repository and ticket match; ask if the original branch cannot be established.
2. Require the original checkout to have no user changes that could be overwritten. Stop and ask if it is not clean.
3. Back up `git diff --binary HEAD` and all non-ignored untracked files to a task-specific temporary directory. Verify the backup before removing anything.
4. Ensure the original task branch can reach the task worktree's HEAD by fast-forward, or already contains it. Create the branch at that HEAD only if absent. If histories diverge, stop without resetting or force-updating. If another checkout occupies the branch, verify its task identity and clean state before freeing it by detaching at its current commit. Stop and ask if it has changes or belongs to another task.
5. Preserve ignored artifacts before removing only the matching task worktree. Switch the original checkout to the original task branch and fast-forward to the recorded task HEAD if needed. Apply the tracked patch and restore untracked files without overwriting existing files. Preserve changes as uncommitted unless the user requested commits. If the task worktree was already removed, perform only the remaining branch-transfer steps.
6. Run `git diff --check` and report the branch and `git status --short` for every original checkout. Delete only temporary backups created by this run after successful verification. Retain preserved artifacts that have not been restored and report their location.

After a successful transfer, the original checkout on the task branch becomes
the active workspace for that ticket. A later implementation request for the
same ticket must continue there unless the user explicitly requests a new
worktree or the checkout now contains unrelated user changes.

If switching, applying, or restoring cannot finish without conflicts, preserve the backup, stop this workflow, and explicitly propose continuing with the [`fix-merge-conflicts`](../fix-merge-conflicts/SKILL.md) skill. Do not resolve conflicts ad hoc.

Complete only when every affected original checkout is on the original task branch and contains all tracked and untracked task changes.
