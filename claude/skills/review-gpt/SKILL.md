---
name: review-gpt
description: Get an independent second-opinion code review of the current task's changes from a GPT model via the pi agent CLI. Use when the user invokes /review-gpt.
disable-model-invocation: true
argument-hint: "[model=openai-codex/gpt-6.1-sol] [thinking=high] [extra focus]"
---

Run a read-only review through `pi`, then triage its findings for the user. Never apply fixes from the review yourself: the output of this skill is a proposal.

## 1. Parse arguments

- `model=<id>`: default `openai-codex/gpt-6.1-sol`. Check unknown ids with `pi --list-models <search>`.
- `thinking=<level>`: default `high` (`off|minimal|low|medium|high|xhigh|max`).
- Any remaining text is an extra review focus.

## 2. Write the brief

Write the brief to a temp file (`mktemp /tmp/review-gpt.XXXXXX.md`). Start it with `/skill:code-review` followed by a space, not a line break (pi reads the skill name up to the first space), so pi loads its `code-review` skill, which defines the review process and report format. The reviewer sees nothing of this conversation, so the rest of the brief must stand alone:

- Repository path(s) and the review scope in `code-review` terms: `branch` with its fixed point, `working-tree`, or `all`. For multiple repositories, list each.
- Goal of the change: ticket id and its requirement, in your own summary. This is the spec for the Spec axis.
- Agreed constraints and deliberate decisions, so they are not reported as defects.
- Extra focus from the arguments.
- Instructions: read-only, do not modify files or apply fixes. Answer in Russian.

Done when a reader with only the brief and the repository could review the change without guessing its intent.

## 3. Run pi in background

Run from the repository root with `run_in_background: true`:

```bash
pi -p --no-session --model "$MODEL" --thinking "$THINKING" --tools read,bash < "$BRIEF"
```

Pass the brief on stdin, not as `@"$BRIEF"`: pi expands `/skill:` only at the very start of the message, and `@file` wraps the content in a `<file>` tag. stdout contains only the agent's final answer. Do not poll; wait for the completion notification.

## 4. Triage

Verify every finding against the actual code before judging it. Report to the user:

- **Стоит исправить**: confirmed problems, with the proposed change.
- **Спорно**: real trade-offs or needs the user's decision, with your view.
- **Отклонить**: false positives or contradictions of agreed decisions, with the evidence.

Done when every finding sits in exactly one group with its reason. Then stop and wait for the user to choose what to fix. Delete the brief file.
