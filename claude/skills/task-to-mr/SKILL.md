---
name: task-to-mr
description: Take a SpaceHub task from its URL to an open, reviewed GitLab merge request with a final pipeline status, unattended.
argument-hint: "<SpaceHub task URL or T-ID> [constraints]"
disable-model-invocation: true
---

# Task to MR

The user invoked this because they are not watching. Your updates go unread
until you stop, and a question waits hours for an answer. You own the task from
its URL to open merge requests whose pipelines reached a final status. Decide
what you can; ask only under "Asking".

Constraints in the arguments override the defaults below.

## Grant

The invocation is the user's explicit instruction to implement the task. It
replaces the ask-first step of the workflows below for:

- creating the task branch or worktree under `task-worktree`;
- commits, normal pushes to the task branch, and creating or updating its
  non-draft MR: `mr-echat` ships without its confirmation step;
- the local stand: starting it, browser checks, and writes to local databases
  through `echat-browser-check` / `echat-adm-browser-check` with the `local`
  profile, and local migrations through `echat-migrations`;
- retrying one flaky CI job under `babysit-mr`;
- adding MR links to the task's `Merge requests` artifact in SpaceHub.

Outside the grant: merge, `container_build`, `deploy:*`, any force push,
queries, migrations, or API checks against non-local databases, other SpaceHub
writes (statuses, time, comments, other artifacts), replies or reactions in MR
discussions, repositories the task does not need, checks with external side
effects (real invitations, emails, messages to customers), and RIES
functionality. Project instructions still apply; the grant removes only the
ask-first step.

## Steps

1. **Read the task.** Fetch it with
   [`fetch-spacehub-task`](../fetch-spacehub-task/SKILL.md) and analyze it under
   [`analyze-spacehub-task`](../analyze-spacehub-task/SKILL.md); its read-only
   default does not apply. Done when you can state the goal, the acceptance
   behavior, the affected repositories, and every open product question.
2. **Decide or ask.** A question that changes the result (several reasonable
   behaviors, a contradiction the code cannot settle, a missing requirement)
   goes to the user under "Asking", all of them in one message. Settle the rest
   with the default closest to the task and current behavior, and record each
   as a decision.
3. **Branch.** Fetch the base and follow
   [`task-worktree`](../task-worktree/SKILL.md): branch contract, hotfix base,
   isolation, and dependencies.
4. **Implement** the smallest change that reaches the goal, under the
   repository's coding standards. Fix the case the task describes, not every
   case that could exist.
5. **Prove** under [`prove-it-works`](../prove-it-works/SKILL.md):
   - In every changed repository, run the commands its CI validate jobs run
     (read `.gitlab-ci.yml`) on the whole project, not only the changed files.
   - For a bug, reproduce the failure, then watch the same reproduction pass.
   - For UI, check the real page with `echat-browser-check`
     (`echat-adm-browser-check` for `tidy-adm`).
   - Add one focused test only when the behavior has none and the repository
     has a test setup.

   Done when every change in the diff has evidence observed in this session,
   and every check is green or its failure is shown on the base too.
6. **Review.** Follow [`review-gpt`](../review-gpt/SKILL.md) with `mode=auto`
   over the whole change against the base. When the change touches shared
   state, protocols, lifecycle code, or external boundaries, run
   [`blast-radius`](../blast-radius/SKILL.md) too. Repeat the step 5 checks
   that cover each fix.
7. **Publish** with [`mr-echat`](../mr-echat/SKILL.md). First stage exactly
   the task's files with `git add <paths>`, so its scope is `staged` and
   changes that existed before the task stay out of the commit. Its `notes.md` carries
   the intent, the step 2 decisions, the exact checks and results, and the
   review outcome. For several repositories use its batch and `link`.
8. **Link the task.** Read the task again with `get_issue`. In the artifact
   titled exactly `Merge requests`, add each missing MR URL on its own line
   without captions, keeping the existing lines (`update_artifact` with the
   full text). Without that artifact, create it with `create_artifact`, title
   `Merge requests`, no template. Read the task back to confirm.
9. **Pipeline.** Follow [`babysit-mr`](../babysit-mr/SKILL.md) with
   `--until pipeline` for every MR. Fix failures the diff caused, prove the
   fix, push, and wait again. Done when each head pipeline is `success` or
   `manual`.
10. **Report.**

Stay active from step 3 to step 10. A final message before step 10 ends the
work, because nobody prompts you again. Wait for the reviewer and `mr-wait`
through their completion notifications.

## Asking

Ask only when you cannot continue alone:

- a product question from step 2;
- the change cannot be proven without an action outside the grant;
- a failure outside the diff blocks a check or the pipeline;
- the next step is outside the grant;
- the task is already solved, obsolete, or needs decomposition into several
  task branches.

Finish everything that does not depend on the answer first. Then ask once with
the full context: task link, MR links, what blocks you, and the options with
your recommendation first. Use the harness's question tool when it has one;
otherwise end the turn with the question as the first line of the final
message.

## Report

Write in the user's language and lead with the outcome:

- MR links, head SHA, final pipeline status with its link;
- proof: checks with results, reproduction, browser checks;
- review: rounds, model, fixed, declined, and disputed findings with both sides;
- the `Merge requests` artifact update;
- the decisions you made for the user;
- unverified risks;
- what remains for the user: `container_build`, deploys, colleague review, and
  `needs user` findings.
