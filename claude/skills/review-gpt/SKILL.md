---
name: review-gpt
description: Get an independent second-opinion code review of the current task's changes from a GPT model via pi, in a T3 Code thread or the pi CLI. Use when the user invokes /review-gpt.
disable-model-invocation: true
argument-hint: "[model=openai-codex/gpt-6.1-sol] [thinking=high] [mode=auto] [extra focus]"
---

Run a read-only review through pi, then triage its findings. By default the output is a proposal for the user: never apply fixes from the review yourself. `mode=auto`, used by [`task-to-mr`](../task-to-mr/SKILL.md), replaces the stop after triage with the fix loop in section 5.

## 1. Parse arguments

- `model=<id>`: default `openai-codex/gpt-6.1-sol`. Check unknown ids with `orchestrator_capabilities` (`search`) in T3 Code, otherwise `pi --list-models <search>`.
- `thinking=<level>`: default `high` (`off|minimal|low|medium|high|xhigh|max`).
- `mode=auto`: run the fix loop in section 5.
- Any remaining text is an extra review focus.

## 2. Write the brief

The reviewer must load pi's `code-review` skill, which defines the review process and report format. How the brief starts depends on the route in section 3:

- **T3 Code**: start with `Make a code review of the change below.` T3 does not pass the message to pi as typed, so a `/skill:` prefix arrives unexpanded; pi picks the skill by its description instead.
- **CLI**: write the brief to a temp file (`mktemp /tmp/review-gpt.XXXXXX.md`) and start it with `/skill:code-review` followed by a space, not a line break (pi reads the skill name up to the first space).

The reviewer sees nothing of this conversation, so the rest of the brief must stand alone:

- Repository path(s) and the review scope in `code-review` terms: `branch` with its fixed point, `working-tree`, or `all`. For multiple repositories, list each.
- Goal of the change: ticket id and its requirement, in your own summary. This is the spec for the Spec axis.
- Agreed constraints and deliberate decisions, so they are not reported as defects.
- Extra focus from the arguments.
- Instructions: read-only, do not modify files or apply fixes. Number findings `S1`, `S2`, ... Flag code, tests, or guards the goal does not need. Answer in Russian.

When preparing a repeat review after an identity or async-state finding was fixed, first run a narrow, read-only [blast-radius](../blast-radius/SKILL.md) pass on the already established invariant, not just the previously flagged line. Include the invariant, affected operations, and current evidence or explicit gaps from that pass in the brief. This does not require another reviewer or a full-suite rerun without a concrete reason, and does not authorize fixes beyond the user's selected scope.

Done when a reader with only the brief and the repository could review the change without guessing its intent.

## 3. Run the reviewer

Choose the route once per review: **T3 Code** when its `delegate_task` tool is available (load it with ToolSearch if it is deferred), otherwise **CLI**. Both routes run in the background: do not poll, wait for the completion notification, and do not edit the reviewed files while the reviewer runs.

### T3 Code

Call `orchestrator_capabilities` once, then `delegate_task` with:

- `task`: the complete brief text;
- `target`: `{providerInstanceId: "pi", model: <model>, options: {thinking: <thinking>}}`;
- `role: "review"`, `mode: "async"`, a new `clientRequestId` per round, `title: "review-gpt <ticket id> round <n>"`.

The child is not tool-restricted the way `--tools read,bash` restricts the CLI, so note `git status --short` of each reviewed repository before the start and confirm it is unchanged after the reply. After the notification, read the reply from `task_status` and record the `model` and `options` it reports. Every round and every repeat review is a fresh `delegate_task` with the full brief, never `t3_thread_send` to an earlier child. A timeout, error, or empty reply is not approval: `task_cancel` the task and start it once more; a second failure is a blocker for the user. If pi or the model is missing from `orchestrator_capabilities`, report that as a blocker; never substitute another model or switch to the CLI unasked.

### CLI

Run from the repository root with `run_in_background: true`:

```bash
pi -p --no-session --model "$MODEL" --thinking "$THINKING" --tools read,bash < "$BRIEF"
```

Pass the brief on stdin, not as `@"$BRIEF"`: pi expands `/skill:` only at the very start of the message, and `@file` wraps the content in a `<file>` tag. stdout contains only the agent's final answer.

If pi exits within seconds and stdout is only `fetch failed`, run the same command once more after 15 seconds without diagnosing the network. Report a second failure to the user as a blocker.

## 4. Triage

Verify every finding against the actual code before judging it. Report to the user:

- **Стоит исправить**: confirmed problems, with the proposed change.
- **Спорно**: real trade-offs or needs the user's decision, with your view.
- **Отклонить**: false positives or contradictions of agreed decisions, with the evidence.

Done when every finding sits in exactly one group with its reason. On the CLI route, delete the brief file after the last round. Without `mode=auto`, stop and wait for the user to choose what to fix.

## 5. Auto mode: fix loop

Grade each confirmed finding yourself, whatever label the reviewer gave it:

- **blocker**: the intended case is wrong.
- **should**: a real bug callers will hit within the goal.
- **nit**: everything else: other paths, rare cases, small performance costs, extra compatibility, style.

Keep a ledger in the conversation: id, grade, outcome (`fixed`, `declined`, `disputed`, `needs user`), evidence.

1. Fix every open blocker and should with the smallest change; prefer deleting or narrowing code over a new lock, cache, helper, or option. Decline nits and out-of-goal findings in one line each; they become follow-ups. A finding that needs a product decision is `needs user`: do not guess it.
2. Disagree with evidence (file:line, test, output) when the finding is wrong. Never agree just to end the loop.
3. Rerun the checks that cover the fixes and compare `git diff --shortstat <base>` with the previous round. If review grew the diff beyond the goal, cut first.
4. Start the next round only while a blocker or should is open or a fix changed behavior code. Reuse the round 1 brief and add the ledger and the instruction: review only code changed since the last round and the open ids; mark each old id `resolved` or `still open: <reason>`.

Budget: 3 rounds. Extend to 5 only for security, permissions, data loss, or state and concurrency, while a blocker or should stays open with evidence. A round with no blocker or should ends the loop; declined nits and comment or format-only fixes need no new round.

Done when the latest round leaves no open blocker or should and the checks pass after the last fix, or the budget ends. Budget end and an item disputed after two replies are not approval: record both sides in 2-3 lines each for the caller's report. Return the ledger, rounds run, model, and diff size before and after.
