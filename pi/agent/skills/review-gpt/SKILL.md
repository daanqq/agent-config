---
name: review-gpt
description: Get an independent second-opinion code review of the current task's changes from a GPT model, then triage the findings without applying fixes.
disable-model-invocation: true
---

Run a read-only review through a Pi child agent, then triage its findings for the user. Never apply fixes from the review yourself: the output of this skill is a proposal.

Invoke with `/skill:review-gpt [model=<id>] [thinking=<level>] [extra focus]`, or `$review-gpt` with the same options in T3 Code. Parse options from the user request accompanying the loaded skill.

## 1. Parse arguments

- `model=<id>`: default `openai-codex/gpt-6.2-sol`. Check unknown ids with `pi --list-models <search>`.
- `thinking=<level>`: default `high` (`off|minimal|low|medium|high|xhigh|max`).
- Any remaining text is an extra review focus.

Read `../subagents/SKILL.md` before spawning. This skill's explicit model and thinking defaults override the general model-selection defaults; user-provided options override this skill's defaults.

## 2. Build the reviewer prompt

Start the prompt with `/skill:code-review` followed by a space, not a line break, so the reviewer loads its `code-review` skill, which defines the review process and report format. Pi expands the command only at the very start of the prompt and reads the skill name up to the first space. On the T3 Code route start with `$code-review` instead: T3 prepends a role line to the task, and the T3 Code bridge expands `$code-review` anywhere in the message. The reviewer sees nothing of this conversation, so the rest of the prompt must stand alone:

- Repository path(s) and the review scope in `code-review` terms: `branch` with its fixed point, `working-tree`, or `all`. For multiple repositories, list each.
- Goal of the change: ticket id and its requirement, in your own summary. This is the spec for the Spec axis.
- Agreed constraints and deliberate decisions, so they are not reported as defects.
- Extra focus from the arguments.
- Instructions: read-only, do not modify files or apply fixes. Answer in Russian.

Done when a reader with only the prompt and the repository could review the change without guessing its intent. Pass the prompt directly to the tool; no temporary brief file is needed.

## 3. Spawn the reviewer

Use the route chosen in `../subagents/SKILL.md`. The reviewer runs in the background: do not poll or immediately wait, and continue useful read-only parent work, such as inspecting the changed code for later triage.

**T3 Code.** Call `delegate_task` once with:

- `task`: the complete reviewer prompt.
- `title`: `review-gpt`; `role`: `review`; `mode`: `async`.
- `target`: `{providerInstanceId: "pi", model: <parsed model id>, options: {thinking: <parsed thinking level>}}`.

The child works in this thread's checkout and is not restricted to read-only tools, so note `git status --short` of each reviewed repository before the start and confirm it is unchanged after the reply. Read the reply with `task_status` after the completion notification.

**Subagents extension.** Call `subagent_spawn` once with:

- `prompt`: the complete reviewer prompt.
- `name`: `review-gpt`.
- `harness`: `pi`.
- `working_dir`: the absolute repository root, or the primary repository root when reviewing multiple repositories.
- `model`: the parsed model id.
- `reasoning_effort`: the parsed thinking level.

Call `subagent_wait({ ids: [id] })` only when you cannot proceed without the result, using the id returned by the spawn.

## 4. Triage

Verify every finding against the actual code before judging it. Report to the user in Russian, grouping findings as:

- **Worth fixing**: confirmed problems, with the proposed change.
- **Debatable**: real trade-offs or needs the user's decision, with your view.
- **Reject**: false positives or contradictions of agreed decisions, with the evidence.

Done when every finding sits in exactly one group with its reason. If there are no significant findings, say so explicitly. Then stop and wait for the user to choose what to fix. Do not apply fixes.
