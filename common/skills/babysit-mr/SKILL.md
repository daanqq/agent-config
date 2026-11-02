---
name: babysit-mr
description: Wait for a GitLab merge request's pipeline and review activity, and fix what the change broke. Use when asked to wait for, watch, or babysit an MR or its pipeline.
compatibility: Requires Python 3.10+ and glab authenticated for the MR host.
---

# Babysit MR

## Waiting

Wait only through `scripts/mr-wait` from this skill's directory (use its
absolute path). Never write your own polling, `until`, or `sleep` loop: hand-made
loops have run silently for hours on a lost cwd or a status they never matched.

```bash
mr-wait <mr-url> [--until pipeline|any-change] [--timeout 90]
```

- `pipeline` (default) exits when the head pipeline reaches a final status.
  `manual` is final: the pipeline passed and stopped at a manual job such as
  `container_build`. Report it at once; it will not move on its own.
- `any-change` exits on the first new event. Use it to wait for reviewers.

It prints one line per event and exits 0 when the condition is met or the MR
merged, 1 when it needs you (failed or canceled pipeline, conflicts, no pipeline
for the head, closed MR, timeout, GitLab unreachable), 2 on bad input or when
another watcher already holds the MR. On 2 from a live watcher, do not start a
second one.

Run it with a monitor that wakes you on each line when the harness has one
(Claude Code: Monitor); otherwise as one background command and wait for its
exit notification. Start it again after every push and after handling an exit 1.
It remembers reported events, so nothing that arrived in between is lost. When
an event needs no action, stay silent; never post "still waiting".

## Pipeline failures

Read the failed job's log (`glab ci trace <job-id>` in the repository, or
`glab api projects/<id>/jobs/<job-id>/trace`) before changing anything, and
classify the failure:

- **Caused by the diff**: reproduce it locally with the job's command, fix it,
  rerun that command, push, and restart the watcher.
- **Infrastructure flake** (runner, network, registry, cache, timeout with no
  code signal): retry that job once with `glab ci retry <job-id>`. A second
  identical failure is a blocker to report.
- **Already failing on the target branch**: check the target's latest pipeline.
  Report it with the link instead of fixing unrelated code.

Never start manual jobs (`container_build`, `deploy:*`) or retry anything beyond
one flake without an explicit user instruction.

## Review activity

Comments, threads, approvals, and change requests are news, not orders. Handle
unresolved discussions with the
[`fix-gitlab-mr-review`](../fix-gitlab-mr-review/SKILL.md) workflow: it owns
triage, mechanical fixes, product-decision questions, and reply approval.

Keep the MR at the size its goal needs. Review loops grow an MR one
cheap-looking fix at a time: fix real bugs in the intended case, decline the
rest with a reason and list them as follow-ups.

## Target branch

When `mr-wait` reports that the target moved and touches this MR's files, or
that the MR conflicts, update the branch with the repository's documented method
(EChat: `git merge origin/<target>`, never rebase or force-push without an
explicit request), recheck the touched behavior, push, and restart the watcher.
Without an earlier instruction to keep the MR current, report it instead.

## Done

Done when `mr-wait --until pipeline` exits 0 on the current head and every event
it printed is fixed, reported, or deliberately left to the user. Report the MR
link, head SHA, final pipeline status with its link, and what remains manual.
