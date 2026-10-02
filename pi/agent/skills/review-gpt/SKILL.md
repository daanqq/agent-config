---
name: review-gpt
description: Get an independent second-opinion code review of the current task's changes from a GPT model, then triage the findings without applying fixes.
disable-model-invocation: true
---

Run a read-only review through a Pi subagent, then triage its findings for the user. Never apply fixes from the review yourself: the output of this skill is a proposal.

Invoke with `/skill:review-gpt [model=<id>] [thinking=<level>] [extra focus]`, or `$review-gpt` with the same options through the local skill-dollar extension. Parse options from the user request accompanying the loaded skill.

## 1. Parse arguments

- `model=<id>`: default `openai-codex/gpt-6.1-sol`. Check unknown ids with `pi --list-models <search>`.
- `thinking=<level>`: default `high` (`off|minimal|low|medium|high|xhigh|max`).
- Any remaining text is an extra review focus.

Read `../subagents/SKILL.md` before spawning. This skill's explicit model and thinking defaults override the general model-selection defaults; user-provided options override this skill's defaults.

## 2. Build the reviewer prompt

The reviewer sees nothing of this conversation, so build a self-contained prompt containing:

- Repository path(s) and how to see the change: base ref / commit range, or "uncommitted working tree" (`git diff`, `git status`). For multiple repositories, list each.
- Goal of the change: ticket id and its requirement, in your own summary.
- Agreed constraints and deliberate decisions, so they are not reported as defects.
- Extra focus from the arguments.
- Instructions: read-only, do not modify files or apply fixes; inspect the diff and surrounding code; report findings ordered by severity, each with `file:line`, the problem, why it matters, and a suggested fix; say explicitly when nothing significant is found. Answer in Russian.

Done when a reader with only the prompt and the repository could review the change without guessing its intent. Pass the prompt directly to the tool; no temporary brief file is needed.

## 3. Spawn the reviewer

Call `subagent_spawn` once with:

- `prompt`: the complete reviewer prompt.
- `name`: `review-gpt`.
- `harness`: `pi`.
- `working_dir`: the absolute repository root, or the primary repository root when reviewing multiple repositories.
- `model`: the parsed model id.
- `reasoning_effort`: the parsed thinking level.

Results arrive automatically. Do not poll or immediately wait. Continue useful read-only parent work, such as inspecting the changed code for later triage. Call `subagent_wait({ ids: [id] })` only when you cannot proceed without the result, using the id returned by the spawn.

## 4. Triage

Verify every finding against the actual code before judging it. Report to the user in Russian, grouping findings as:

- **Worth fixing**: confirmed problems, with the proposed change.
- **Debatable**: real trade-offs or needs the user's decision, with your view.
- **Reject**: false positives or contradictions of agreed decisions, with the evidence.

Done when every finding sits in exactly one group with its reason. If there are no significant findings, say so explicitly. Then stop and wait for the user to choose what to fix. Do not apply fixes.
