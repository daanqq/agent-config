---
description: Split current repo changes into logical commits and push them
argument-hint: "[instructions]"
---
Commit and push all current repository changes.

First inspect every staged, unstaged, and untracked change. Decide how the changes should be divided into logical, independently understandable commits. Use multiple commits when the changes contain distinct concerns; use a single commit when splitting would not improve clarity. Do not split mechanically by file, and do not combine unrelated changes.

For each commit:
1. Stage only the files or hunks that belong to that commit.
2. Inspect the staged diff and verify that it is coherent and does not include changes intended for another commit.
3. Write a concise commit message that accurately summarizes the staged change.
4. Commit it, then continue until every current repository change has been committed exactly once.

After all commits are created:
1. Push them to the current branch's remote.
   - If the current branch does not have an upstream remote branch, create one by pushing with upstream tracking.
   - If this repository has no git remotes configured, do not push.
2. Output a short list of the commits created, in order.
3. If the repository has a remote, output the remote URL for what was pushed.
   - If the current branch is `main` or `master`, output the normal remote repository URL.
   - If the current branch is neither `main` nor `master`, output a URL to create a pull request from the pushed branch into `main` or `master`.
   - Convert SSH git remotes like `git@github.com:owner/repo.git` to HTTPS URLs when printing.

Additional instructions from the user:
$ARGUMENTS
